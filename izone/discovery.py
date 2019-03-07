"""Internal discovery service for  iZone AC."""

import logging
from asyncio import Event
from typing import Dict

from homeassistant.const import CONF_EXCLUDE, EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

from .climate import ControllerDevice
from .constants import DATA_ADD_ENTRIES, DATA_CONFIG, DATA_DISCOVERY_SERVICE

_LOGGER = logging.getLogger(__name__)


async def async_start_discovery_service(hass: HomeAssistantType):
    """Set up the pychromecast internal discovery."""
    import pizone

    class DiscoveryService(pizone.Listener):
        """Discovery data and interfacing with pizone library."""

        def __init__(self):
            self.controllers: Dict[str, pizone.Controller] = {}
            self.controller_ready = Event()
            self.components: Dict[pizone.Controller, 'IZoneController'] = {}

            self.pi_disco = None
            self.stop_listener = None

        # Listener interface
        def controller_disconnected(self, ctrl: pizone.Controller,
                                    ex: Exception) -> None:
            """Disconnected from contrller."""
            component = self.components.get(ctrl)
            if not component:
                return
            component.set_available(False)

        def controller_reconnected(self, ctrl: pizone.Controller) -> None:
            """Reconnected to controller."""
            component = self.components.get(ctrl)
            if not component:
                return
            component.set_available(True)

        async def _controller_discovered(self, ctrl: pizone.Controller):
            _LOGGER.debug("Controller discovered uid=%s", ctrl.device_uid)

            conf: ConfigType = hass.data.get(DATA_CONFIG)

            # Filter out any entities excluded in the config file
            if conf and ctrl.device_uid in conf[CONF_EXCLUDE]:
                return

            self.controllers[ctrl.device_uid] = ctrl
            self.controller_ready.set()

            # This will be present if the component is configured.
            # otherwise init_controller will be called when the config entry
            # is created.
            async_add_entries = hass.data.get(DATA_ADD_ENTRIES)
            if async_add_entries:
                self.init_controller(ctrl, async_add_entries)

        def init_controller(self, controller: pizone.Controller,
                            async_add_entries):
            """Register the controller device and the containing zones."""
            device = ControllerDevice(controller, async_add_entries)
            self.components[controller] = device

        def controller_discovered(self, ctrl: pizone.Controller) -> None:
            assert ctrl.device_uid not in self.controllers, \
                "discovered device that already exists"

            hass.async_create_task(self._controller_discovered(ctrl))

        def controller_update(self, ctrl: pizone.Controller) -> None:
            component = self.components.get(ctrl)
            if not component:
                return

            hass.async_add_job(component.async_update_ha_state)

        def zone_update(self, ctrl: pizone.Controller,
                        zone: pizone.Zone) -> None:
            if zone.type == pizone.Zone.Type.CONST:
                return

            component = self.components.get(ctrl)
            if not component:
                return

            zone_component = component.zones[zone]
            hass.async_add_job(zone_component.async_update_ha_state)

    disco = hass.data.get(DATA_DISCOVERY_SERVICE)
    if disco:
        # Already started
        return disco

    # discovery local services
    disco = DiscoveryService()
    hass.data[DATA_DISCOVERY_SERVICE] = disco

    # Start the pizone discovery service, disco is the listener
    session = aiohttp_client.async_get_clientsession(hass)
    loop = hass.loop

    disco.pi_disco = pizone.discovery(disco, loop=loop, session=session)
    await disco.pi_disco.start_discovery()

    async def shutdown_event(event):
        await disco.pi_disco.close()
        del hass.data[DATA_DISCOVERY_SERVICE]

    disco.stop_listener = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, shutdown_event)

    return disco


async def async_stop_discovery_service(hass: HomeAssistantType):
    """Stop the discovery service."""
    disco = hass.data.get(DATA_DISCOVERY_SERVICE)
    if not disco:
        return

    disco.stop_listener()
    await disco.pi_disco.close()
    del hass.data[DATA_DISCOVERY_SERVICE]
    del hass.data[DATA_ADD_ENTRIES]
