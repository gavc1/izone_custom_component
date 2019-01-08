"""
Support for the iZone HVAC.

For more details about this platform, please refer to the documentation at
https://github.com/Swamp-Ig/izone_custom_component
"""
import logging
from typing import cast

from custom_components.izone.constants import (DATA_ADD_ENTRIES,
                                               DATA_DISCOVERY_SERVICE, DOMAIN)
from homeassistant.components.climate import (STATE_AUTO, STATE_COOL,
                                              STATE_DRY, STATE_FAN_ONLY,
                                              STATE_HEAT, SUPPORT_FAN_MODE,
                                              SUPPORT_ON_OFF,
                                              SUPPORT_OPERATION_MODE,
                                              SUPPORT_TARGET_TEMPERATURE,
                                              ClimateDevice)
from homeassistant.const import (ATTR_TEMPERATURE, PRECISION_HALVES,
                                 STATE_OPEN, STATE_CLOSED, TEMP_CELSIUS)
from homeassistant.helpers.temperature import display_temp as show_temp
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

DEPENENCIES = ['izone']

_LOGGER = logging.getLogger(__name__)

# TODO: add this state to the component states list.
# will need adding to the front-end strings as well.
STATE_OUTSIDE_AIR = 'outside_air'


async def async_setup_entry(hass: HomeAssistantType, config: ConfigType,
                            async_add_entities):
    """Initialize an IZone Controller."""
    disco = hass.data[DATA_DISCOVERY_SERVICE]

    # create any components not yet created
    for controller in disco.controllers.values():
        disco.init_controller(controller, async_add_entities)

    # disco will use the register function to register any further components
    hass.data[DATA_ADD_ENTRIES] = async_add_entities

    return True


class ControllerDevice(ClimateDevice):
    """Representation of iZone Controller."""

    def __init__(self, controller, async_add_entities) -> None:
        """Initialise ControllerDevice."""
        from pizone import Controller, Zone

        self._controller = cast(Controller, controller)

        self._supported_features = (SUPPORT_OPERATION_MODE |
                                    SUPPORT_FAN_MODE | SUPPORT_ON_OFF)

        if ((controller.ras_mode == 'master' and controller.zone_ctrl == 13) or
                controller.ras_mode == 'RAS'):
            self._supported_features |= SUPPORT_TARGET_TEMPERATURE

        self._state_to_pizone = {
            STATE_COOL: Controller.Mode.COOL,
            STATE_HEAT: Controller.Mode.HEAT,
            STATE_AUTO: Controller.Mode.AUTO,
            STATE_FAN_ONLY: Controller.Mode.VENT,
            STATE_DRY: Controller.Mode.DRY,
        }
        if controller.free_air_enabled:
            # TODO: when added to the climate states, remove this
            label = STATE_OUTSIDE_AIR.title().replace('_', ' ')
            self._state_to_pizone[label] = Controller.Mode.FREE_AIR

        self._fan_to_pizone = {}
        for fan in controller.fan_modes:
            self._fan_to_pizone[fan.name.title()] = fan

        # Create the zones
        self.zones = {}
        for zone in controller.zones:
            if zone.type != Zone.Type.CONST:
                self.zones[zone] = ZoneDevice(self, zone)

        self._device_info = {
            'identifiers': {
                (DOMAIN, self.unique_id)
            },
            'name': self.name,
            'manufacturer': 'IZone',
            'model': self._controller.sys_type,
        }

        entities = [self]
        entities.extend(self.zones.values())
        async_add_entities(entities, True)

        self._available = True

        _LOGGER.info("Controller UID=%s is ready", controller.device_uid)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def assumed_state(self) -> bool:
        """Return True if unable to access real state of the entity."""
        return not self._available

    def set_available(self, available: bool) -> None:
        """
        Set availability for the controller.

        Also sets zone availability as they follow the same availability.
        """
        if self.available == available:
            return

        if available:
            _LOGGER.error(
                "Reconnected controller %s ",
                self._controller.device_uid)
        else:
            _LOGGER.error(
                "Unable to contact controller %s",
                self._controller.device_uid)

        self._available = available

    @property
    def device_info(self):
        """Return the device info for the iZone system."""
        return self._device_info

    @property
    def unique_id(self):
        """Return the ID of the controller device."""
        return DOMAIN + '_' + self._controller.device_uid

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._controller.device_uid

    @property
    def should_poll(self) -> bool:
        """Return True if entity has to be polled for state.

        False if entity pushes its state to HA.
        """
        return False

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._supported_features

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        return TEMP_CELSIUS

    @property
    def precision(self):
        """Return the precision of the system."""
        return PRECISION_HALVES

    @property
    def state_attributes(self):
        """Return the optional state attributes."""
        data = super().state_attributes
        data['supply_temperature'] = show_temp(
            self.hass, self.supply_temperature, self.temperature_unit,
            self.precision)
        return data

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool, idle."""
        mode = self._controller.mode
        for (key, value) in self._state_to_pizone.items():
            if value == mode:
                return key
        assert False, "Should be unreachable"

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return list(self._state_to_pizone.keys())

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._controller.temp_return

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._controller.temp_setpoint

    @property
    def supply_temperature(self):
        """Return the current supply, or in duct, temperature."""
        return self._controller.temp_supply

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def is_on(self):
        """Return true if on."""
        return self._controller.is_on

    @property
    def current_fan_mode(self):
        """Return the fan setting."""
        return self._controller.fan.name.title()

    @property
    def fan_list(self):
        """Return the list of available fan modes."""
        return list(self._fan_to_pizone.keys())

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self._controller.temp_min

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return self._controller.temp_max

    async def _wrap_and_catch(self, coro):
        try:
            await coro
            self.set_available(True)
        except ConnectionError:
            self.set_available(False)

    def async_set_temperature(self, **kwargs):
        """Set new target temperature.

        This method must be run in the event loop and returns a coroutine.
        """
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp:
            return self._wrap_and_catch(
                self._controller.set_temp_setpoint(temp))

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode.

        This method must be run in the event loop and returns a coroutine.
        """
        fan = self._fan_to_pizone[fan_mode]
        await self._wrap_and_catch(self._controller.set_fan(fan))

    async def async_set_operation_mode(self, operation_mode):
        """Set new target operation mode.

        This method must be run in the event loop and returns a coroutine.
        """
        mode = self._state_to_pizone[operation_mode]
        await self._wrap_and_catch(self._controller.set_mode(mode))

    async def async_turn_on(self):
        """Turn device on.

        This method must be run in the event loop and returns a coroutine.
        """
        await self._wrap_and_catch(self._controller.set_on(True))

    async def async_turn_off(self):
        """Turn device off.

        This method must be run in the event loop and returns a coroutine.
        """
        await self._wrap_and_catch(self._controller.set_on(False))


class ZoneDevice(ClimateDevice):
    """Representation of iZone Zone."""

    def __init__(self, controller: ControllerDevice, zone) -> None:
        """Initialise ZoneDevice."""
        from pizone import Zone

        self._controller = controller
        self._zone = cast(Zone, zone)

        self._supported_features = 0
        if zone.type == Zone.Type.OPCL:
            self._supported_features = SUPPORT_ON_OFF
        elif zone.type == Zone.Type.AUTO:
            self._state_to_pizone = {
                STATE_CLOSED.title(): Zone.Mode.CLOSE,
                STATE_OPEN.title(): Zone.Mode.OPEN,
                STATE_AUTO: Zone.Mode.AUTO,
            }
            self._supported_features = (SUPPORT_ON_OFF |
                                        SUPPORT_OPERATION_MODE |
                                        SUPPORT_TARGET_TEMPERATURE)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._controller.available

    @property
    def assumed_state(self) -> bool:
        """Return True if unable to access real state of the entity."""
        return self._controller.assumed_state

    @property
    def device_info(self):
        """Return the device info for the iZone system."""
        return self._controller.device_info

    @property
    def unique_id(self):
        """Return the ID of the controller device."""
        return (self._controller.unique_id + '_z' +
                str(self._zone.index+1))

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._zone.name.title()

    @property
    def should_poll(self) -> bool:
        """Return True if entity has to be polled for state.

        False if entity pushes its state to HA.
        """
        return False

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._supported_features

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        return TEMP_CELSIUS

    @property
    def precision(self):
        """Return the precision of the system."""
        return PRECISION_HALVES

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool, idle."""
        mode = self._zone.mode
        for (key, value) in self._state_to_pizone.items():
            if value == mode:
                return key
        return ''

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return list(self._state_to_pizone.keys())

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._zone.temp_current

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._zone.temp_setpoint

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self._controller.min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return self._controller.max_temp

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature.

        This method must be run in the event loop and returns a coroutine.
        """
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp:
            await self._controller._wrap_and_catch(  # pylint: disable=W0212
                self._zone.set_temp_setpoint(temp))

    async def async_set_operation_mode(self, operation_mode):
        """Set new target operation mode.

        This method must be run in the event loop and returns a coroutine.
        """
        mode = self._state_to_pizone[operation_mode]
        await self._controller._wrap_and_catch(  # pylint: disable=W0212
            self._zone.set_mode(mode))

    @property
    def is_on(self):
        """Return true if on."""
        from pizone import Zone
        return self._zone.mode != Zone.Mode.CLOSE

    async def async_turn_on(self):
        """Turn device on (open zone).

        This method must be run in the event loop and returns a coroutine.
        """
        from pizone import Zone

        if self._zone.type == Zone.Type.CONST:
            await self._controller._wrap_and_catch(  # pylint: disable=W0212
                self._zone.set_mode(Zone.Mode.OPEN))
        else:
            await self._controller._wrap_and_catch(  # pylint: disable=W0212
                self._zone.set_mode(Zone.Mode.AUTO))

    async def async_turn_off(self):
        """Turn device off (close zone).

        This method must be run in the event loop and returns a coroutine.
        """
        from pizone import Zone
        await self._controller._wrap_and_catch(  # pylint: disable=W0212
            self._zone.set_mode(Zone.Mode.CLOSE))
