"""Home Assistant services for Nice IT4WIFI user management.

These services expose the NHK ``PAIRINGS`` / ``USER_NEW`` / ``USER_EDIT``
commands so an administrator can list, approve, re-permission, and remove users
without running scripts by hand. Account names are identifying data, so they are
returned only through the on-demand ``list_users`` service response — never
persisted entity state, attributes, or diagnostics.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .runtime import get_coordinator

SERVICE_LIST_USERS = "list_users"
SERVICE_APPROVE_USER = "approve_user"
SERVICE_SET_USER_PERMISSION = "set_user_permission"
SERVICE_DELETE_USER = "delete_user"
SERVICE_LIST_TRANSMITTERS = "list_transmitters"
SERVICE_DELETE_TRANSMITTER = "delete_transmitter"
SERVICE_ADD_TRANSMITTER = "add_transmitter"
SERVICE_SET_TRANSMITTER_COMMAND = "set_transmitter_command"
SERVICE_LEARN_TRANSMITTER = "learn_transmitter"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_USERNAME = "username"
ATTR_PERMISSION = "permission"
ATTR_SERIAL = "serial"
ATTR_BUTTON = "button"
ATTR_COMMAND = "command"
ATTR_TYPE = "type"
ATTR_ROUND = "round"
ATTR_PRIORITY = "priority"
ATTR_GROUP_ABILITATION = "group_abilitation"
ATTR_T4_GROUP = "t4_group"
ATTR_TIMEOUT = "timeout"

SETTABLE_PERMISSIONS = ("admin", "user", "disable")

_SERVICES = (
    SERVICE_LIST_USERS,
    SERVICE_APPROVE_USER,
    SERVICE_SET_USER_PERMISSION,
    SERVICE_DELETE_USER,
    SERVICE_LIST_TRANSMITTERS,
    SERVICE_DELETE_TRANSMITTER,
    SERVICE_ADD_TRANSMITTER,
    SERVICE_SET_TRANSMITTER_COMMAND,
    SERVICE_LEARN_TRANSMITTER,
)


def _parse_serial(value: str) -> int:
    """Parse a transmitter serial given as decimal or 0x-prefixed hex."""
    text = str(value).strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
    except ValueError as err:
        raise HomeAssistantError(
            f"invalid serial {value!r}: use the decimal serial from list_transmitters "
            "or a 0x-prefixed hex value"
        ) from err

_BASE_FIELDS = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
LIST_USERS_SCHEMA = vol.Schema(_BASE_FIELDS)
APPROVE_USER_SCHEMA = vol.Schema(
    {**_BASE_FIELDS, vol.Required(ATTR_USERNAME): cv.string}
)
SET_USER_PERMISSION_SCHEMA = vol.Schema(
    {
        **_BASE_FIELDS,
        vol.Required(ATTR_USERNAME): cv.string,
        vol.Required(ATTR_PERMISSION): vol.In(SETTABLE_PERMISSIONS),
    }
)
DELETE_USER_SCHEMA = vol.Schema(
    {**_BASE_FIELDS, vol.Required(ATTR_USERNAME): cv.string}
)
LIST_TRANSMITTERS_SCHEMA = vol.Schema(_BASE_FIELDS)
DELETE_TRANSMITTER_SCHEMA = vol.Schema(
    {
        **_BASE_FIELDS,
        vol.Required(ATTR_SERIAL): cv.string,
        vol.Optional(ATTR_BUTTON): vol.All(vol.Coerce(int), vol.Range(min=0, max=15)),
    }
)
ADD_TRANSMITTER_SCHEMA = vol.Schema(
    {
        **_BASE_FIELDS,
        vol.Required(ATTR_SERIAL): cv.string,
        vol.Required(ATTR_BUTTON): vol.All(vol.Coerce(int), vol.Range(min=1, max=15)),
        vol.Required(ATTR_COMMAND): vol.All(vol.Coerce(int), vol.Range(min=1, max=15)),
        vol.Optional(ATTR_TYPE, default="mono"): vol.In(("mono", "bidi")),
        vol.Optional(ATTR_ROUND, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=0xFFFF)
        ),
        vol.Optional(ATTR_PRIORITY, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=3)
        ),
        # 12 (0b1100) is what every transmitter stored by the installer / MyNice
        # Pro carries on an OXIBD; 0 is an untested value.
        vol.Optional(ATTR_GROUP_ABILITATION, default=12): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=15)
        ),
        vol.Optional(ATTR_T4_GROUP, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=15)
        ),
    }
)
SET_TRANSMITTER_COMMAND_SCHEMA = vol.Schema(
    {
        **_BASE_FIELDS,
        vol.Required(ATTR_SERIAL): cv.string,
        vol.Required(ATTR_BUTTON): vol.All(vol.Coerce(int), vol.Range(min=1, max=15)),
        vol.Required(ATTR_COMMAND): vol.All(vol.Coerce(int), vol.Range(min=1, max=15)),
    }
)
LEARN_TRANSMITTER_SCHEMA = vol.Schema(
    {
        **_BASE_FIELDS,
        vol.Optional(ATTR_TIMEOUT, default=60): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=180)
        ),
    }
)


def _loaded_entries(hass: HomeAssistant) -> list:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _resolve_coordinator(hass: HomeAssistant, call: ServiceCall):
    """Resolve the target gate coordinator for a service call."""
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id is not None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise HomeAssistantError(
                f"Nice IT4WIFI config entry {entry_id} is not loaded"
            )
        return get_coordinator(entry)

    entries = _loaded_entries(hass)
    if not entries:
        raise HomeAssistantError("No loaded Nice IT4WIFI config entry")
    if len(entries) > 1:
        raise HomeAssistantError(
            "Multiple Nice IT4WIFI gates are configured; pass config_entry_id"
        )
    return get_coordinator(entries[0])


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the user-management services once for the integration."""
    if hass.services.has_service(DOMAIN, SERVICE_LIST_USERS):
        return

    async def async_list_users(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass, call)
        await coordinator.async_refresh_users()
        snapshot = coordinator.user_snapshot
        users = [user.as_dict() for user in snapshot.users] if snapshot else []
        return {"users": users}

    async def async_approve_user(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call)
        await coordinator.async_approve_user(call.data[ATTR_USERNAME])

    async def async_set_user_permission(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call)
        await coordinator.async_set_user_permission(
            call.data[ATTR_USERNAME],
            call.data[ATTR_PERMISSION],
        )

    async def async_delete_user(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call)
        await coordinator.async_delete_user(call.data[ATTR_USERNAME])

    async def async_list_transmitters(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass, call)
        await coordinator.async_refresh_transmitters()
        snapshot = coordinator.transmitter_snapshot
        transmitters = (
            [tx.as_dict() for tx in snapshot.transmitters] if snapshot else []
        )
        return {"transmitters": transmitters}

    async def async_delete_transmitter(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass, call)
        removed = await coordinator.async_delete_transmitter(
            _parse_serial(call.data[ATTR_SERIAL]),
            call.data.get(ATTR_BUTTON),
        )
        return {"removed": [record.as_dict() for record in removed]}

    async def async_add_transmitter(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass, call)
        remote_type = 1 if call.data[ATTR_TYPE] == "bidi" else 0
        record = await coordinator.async_add_transmitter(
            _parse_serial(call.data[ATTR_SERIAL]),
            call.data[ATTR_BUTTON],
            call.data[ATTR_COMMAND],
            remote_type=remote_type,
            round_=call.data[ATTR_ROUND],
            priority=call.data[ATTR_PRIORITY],
            group_abilitation=call.data[ATTR_GROUP_ABILITATION],
            t4_group=call.data[ATTR_T4_GROUP],
        )
        return {"added": record.as_dict()}

    async def async_set_transmitter_command(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass, call)
        record = await coordinator.async_set_transmitter_command(
            _parse_serial(call.data[ATTR_SERIAL]),
            call.data[ATTR_BUTTON],
            call.data[ATTR_COMMAND],
        )
        return {"transmitter": record.as_dict()}

    async def async_learn_transmitter(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass, call)
        learned = await coordinator.async_learn_transmitter(call.data[ATTR_TIMEOUT])
        return {"learned": [record.as_dict() for record in learned]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_USERS,
        async_list_users,
        schema=LIST_USERS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPROVE_USER,
        async_approve_user,
        schema=APPROVE_USER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_USER_PERMISSION,
        async_set_user_permission,
        schema=SET_USER_PERMISSION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_USER,
        async_delete_user,
        schema=DELETE_USER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_TRANSMITTERS,
        async_list_transmitters,
        schema=LIST_TRANSMITTERS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_TRANSMITTER,
        async_delete_transmitter,
        schema=DELETE_TRANSMITTER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_TRANSMITTER,
        async_add_transmitter,
        schema=ADD_TRANSMITTER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TRANSMITTER_COMMAND,
        async_set_transmitter_command,
        schema=SET_TRANSMITTER_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LEARN_TRANSMITTER,
        async_learn_transmitter,
        schema=LEARN_TRANSMITTER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the services once the last gate entry is unloaded."""
    if _loaded_entries(hass):
        return
    for service in _SERVICES:
        hass.services.async_remove(DOMAIN, service)
