"""Sensor platform for mijn.ista.nl."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfTemperature, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, SERVICE_NAME_TRANSLATIONS
from .coordinator import CustomerData, MijnIstaCoordinator

_LOGGER = logging.getLogger(__name__)

# Map API unit strings → HA unit constants
_UNIT_MAP: dict[str, str] = {
    "Gigajoule": UnitOfEnergy.GIGA_JOULE,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "m3": UnitOfVolume.CUBIC_METERS,
    "m³": UnitOfVolume.CUBIC_METERS,
}

# Map API unit strings → HA SensorDeviceClass
_DEVICE_CLASS_MAP: dict[str, SensorDeviceClass | None] = {
    "Gigajoule": SensorDeviceClass.ENERGY,
    "kWh": SensorDeviceClass.ENERGY,
    "m3": SensorDeviceClass.WATER,
    "m³": SensorDeviceClass.WATER,
}


def _translate_service(description: str, language: str) -> str:
    """Return English service name when language is 'en', otherwise pass through."""
    if language == "en":
        return SERVICE_NAME_TRANSLATIONS.get(description, description)
    return description


def _ha_unit(api_unit: str) -> str | None:
    return _UNIT_MAP.get(api_unit)


def _ha_device_class(api_unit: str) -> SensorDeviceClass | None:
    return _DEVICE_CLASS_MAP.get(api_unit)


class MijnIstaSensor(CoordinatorEntity, SensorEntity):
    """A single mijn.ista.nl sensor backed by MijnIstaCoordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MijnIstaCoordinator,
        cuid: str,
        unique_id_suffix: str,
        name: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        value_fn: Callable[[CustomerData], Any],
        attrs_fn: Callable[[CustomerData], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._cuid = cuid
        self._value_fn = value_fn
        self._attrs_fn = attrs_fn
        self._attr_unique_id = f"{DOMAIN}_{cuid}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class

    @property
    def device_info(self) -> DeviceInfo:
        data: CustomerData | None = (
            self.coordinator.data.get(self._cuid) if self.coordinator.data else None
        )
        if data:
            display_name = f"ista NL — {data.city} {data.zip_code}"
            model = ", ".join(s.meter_type for s in data.services if s.meter_type) or "mijn.ista.nl"
        else:
            display_name = f"ista NL — {self._cuid[:8]}"
            model = "mijn.ista.nl"
        return DeviceInfo(
            identifiers={(DOMAIN, self._cuid)},
            name=display_name,
            manufacturer=MANUFACTURER,
            model=model,
            configuration_url="https://mijn.ista.nl",
        )

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        customer = self.coordinator.data.get(self._cuid)
        if customer is None:
            return None
        try:
            return self._value_fn(customer)
        except (KeyError, IndexError, TypeError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data or self._attrs_fn is None:
            return {}
        customer = self.coordinator.data.get(self._cuid)
        if customer is None:
            return {}
        try:
            return self._attrs_fn(customer)
        except (KeyError, IndexError, TypeError, AttributeError):
            return {}


# ── sensor factory ──────────────────────────────────────────────────────────


def _build_sensors(
    coordinator: MijnIstaCoordinator,
    cuid: str,
    customer: CustomerData,
) -> list[MijnIstaSensor]:
    """Build the complete sensor list for one property (Cuid)."""
    sensors: list[MijnIstaSensor] = []
    svc_by_id = {s.id: s for s in customer.services}
    lang = coordinator.language

    # ── annual sensors (per service) ────────────────────────────────────────
    for sid, annual in customer.annual.items():
        svc = svc_by_id.get(sid)
        unit = _ha_unit(svc.unit) if svc else None
        dc = _ha_device_class(svc.unit) if svc else None
        label = _translate_service(svc.description, lang) if svc else f"Service {sid}"

        # Current-year total
        sensors.append(
            MijnIstaSensor(
                coordinator, cuid,
                f"svc{sid}_annual_current",
                f"{label} Annual Current",
                unit, dc, SensorStateClass.TOTAL,
                value_fn=lambda c, s=sid: c.annual[s].total_now if s in c.annual else None,
                attrs_fn=lambda c, s=sid: {
                    "period_start": c.annual[s].cur_meters[0].begin_date
                    if c.annual[s].cur_meters else None,
                    "period_end": c.annual[s].cur_meters[0].end_date
                    if c.annual[s].cur_meters else None,
                    "meters": [m.as_dict() for m in c.annual[s].cur_meters],
                } if s in c.annual else {},
            )
        )

        # Previous-year total
        sensors.append(
            MijnIstaSensor(
                coordinator, cuid,
                f"svc{sid}_annual_previous",
                f"{label} Annual Previous",
                unit, dc, SensorStateClass.TOTAL,
                value_fn=lambda c, s=sid: c.annual[s].total_previous if s in c.annual else None,
                attrs_fn=lambda c, s=sid: {
                    "total_whole_year": c.annual[s].total_whole_previous,
                    "meters": [m.as_dict() for m in c.annual[s].comp_meters],
                } if s in c.annual else {},
            )
        )

        # Year-over-year change %
        sensors.append(
            MijnIstaSensor(
                coordinator, cuid,
                f"svc{sid}_annual_diff_pct",
                f"{label} Annual Change",
                PERCENTAGE, None, SensorStateClass.MEASUREMENT,
                value_fn=lambda c, s=sid: c.annual[s].diff_pct if s in c.annual else None,
            )
        )

        # Annual building average (from ConsumptionAverages)
        if sid in customer.building_averages:
            sensors.append(
                MijnIstaSensor(
                    coordinator, cuid,
                    f"svc{sid}_building_avg_annual",
                    f"{label} Building Average Annual",
                    unit, dc, SensorStateClass.MEASUREMENT,
                    value_fn=lambda c, s=sid: c.building_averages.get(s),
                )
            )

        # Per-meter annual sensors (current year)
        for meter in annual.cur_meters:
            sensors.append(
                MijnIstaSensor(
                    coordinator, cuid,
                    f"svc{sid}_dev{meter.meter_id}_annual",
                    f"{label} Meter {meter.serial_nr} Annual",
                    unit, dc, SensorStateClass.TOTAL,
                    value_fn=lambda c, s=sid, mid=meter.meter_id: next(
                        (m.c_value for m in c.annual[s].cur_meters if m.meter_id == mid),
                        None,
                    ) if s in c.annual else None,
                    attrs_fn=lambda c, s=sid, mid=meter.meter_id: next(
                        (m.as_dict() for m in c.annual[s].cur_meters if m.meter_id == mid),
                        {},
                    ) if s in c.annual else {},
                )
            )

    # ── monthly sensors (per service, based on latest month entry) ──────────
    if customer.monthly:
        latest = customer.monthly[0]

        for sid, month_svc in latest.services.items():
            svc = svc_by_id.get(sid)
            unit = _ha_unit(svc.unit) if svc else None
            dc = _ha_device_class(svc.unit) if svc else None
            label = _translate_service(svc.description, lang) if svc else f"Service {sid}"

            # Monthly total (latest month, prior months in attributes)
            sensors.append(
                MijnIstaSensor(
                    coordinator, cuid,
                    f"svc{sid}_month_latest",
                    f"{label} Current Month",
                    unit, dc, SensorStateClass.TOTAL,
                    value_fn=lambda c, s=sid: (
                        c.monthly[0].services[s].total_consumption
                        if c.monthly and s in c.monthly[0].services
                        else None
                    ),
                    attrs_fn=lambda c, s=sid: {
                        "month": f"{c.monthly[0].year}-{c.monthly[0].month:02d}"
                        if c.monthly else None,
                        "building_average": c.monthly[0].services[s].building_average
                        if c.monthly and s in c.monthly[0].services else None,
                        "has_approximation": c.monthly[0].services[s].has_approximation
                        if c.monthly and s in c.monthly[0].services else None,
                        "prior_months": [
                            {
                                "year": me.year,
                                "month": me.month,
                                "consumption": me.services[s].total_consumption
                                if s in me.services else None,
                                "building_average": me.services[s].building_average
                                if s in me.services else None,
                            }
                            for me in c.monthly[1:13]
                        ],
                    } if c.monthly else {},
                )
            )

            # Monthly building average
            sensors.append(
                MijnIstaSensor(
                    coordinator, cuid,
                    f"svc{sid}_month_building_avg",
                    f"{label} Month Building Average",
                    unit, dc, SensorStateClass.MEASUREMENT,
                    value_fn=lambda c, s=sid: (
                        c.monthly[0].services[s].building_average
                        if c.monthly and s in c.monthly[0].services
                        else None
                    ),
                    attrs_fn=lambda c, s=sid: {
                        "month": f"{c.monthly[0].year}-{c.monthly[0].month:02d}"
                        if c.monthly else None,
                    } if c.monthly else {},
                )
            )

            # Per physical meter, latest month
            for dev in month_svc.device_consumptions:
                sensors.append(
                    MijnIstaSensor(
                        coordinator, cuid,
                        f"svc{sid}_dev{dev.meter_id}_month",
                        f"{label} Meter {dev.serial_nr} Month",
                        unit, dc, SensorStateClass.TOTAL,
                        value_fn=lambda c, s=sid, did=dev.meter_id: next(
                            (
                                d.c_value
                                for d in c.monthly[0].services[s].device_consumptions
                                if d.meter_id == did
                            ),
                            None,
                        ) if c.monthly and s in c.monthly[0].services else None,
                        attrs_fn=lambda c, s=sid, did=dev.meter_id: next(
                            (
                                d.as_dict()
                                for d in c.monthly[0].services[s].device_consumptions
                                if d.meter_id == did
                            ),
                            {},
                        ) if c.monthly and s in c.monthly[0].services else {},
                    )
                )

    # ── average temperature (per property) ──────────────────────────────────
    sensors.append(
        MijnIstaSensor(
            coordinator, cuid,
            "avg_temp",
            "Average Temperature",
            UnitOfTemperature.CELSIUS,
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
            value_fn=lambda c: c.monthly[0].avg_temp if c.monthly else None,
            attrs_fn=lambda c: {
                "month": f"{c.monthly[0].year}-{c.monthly[0].month:02d}"
                if c.monthly else None,
                "temperature_history": [
                    {"year": me.year, "month": me.month, "avg_temp": me.avg_temp}
                    for me in c.monthly[:24]
                ],
            } if c.monthly else {},
        )
    )

    return sensors


# ── platform setup ──────────────────────────────────────────────────────────


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up mijn.ista.nl sensors from a config entry."""
    coordinator: MijnIstaCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[MijnIstaSensor] = []
    if coordinator.data:
        for cuid, customer in coordinator.data.items():
            built = _build_sensors(coordinator, cuid, customer)
            _LOGGER.debug(
                "mijn.ista.nl: registering %d sensors for cuid=%s", len(built), cuid
            )
            entities.extend(built)

    async_add_entities(entities)
