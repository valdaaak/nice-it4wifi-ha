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

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_USERNAME = "username"
ATTR_PERMISSION = "permission"

SETTABLE_PERMISSIONS = ("admin", "user", "disable")

_SERVICES = (
    SERVICE_LIST_USERS,
    SERVICE_APPROVE_USER,
    SERVICE_SET_USER_PERMISSION,
    SERVICE_DELETE_USER,
)

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


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the services once the last gate entry is unloaded."""
    if _loaded_entries(hass):
        return
    for service in _SERVICES:
        hass.services.async_remove(DOMAIN, service)
