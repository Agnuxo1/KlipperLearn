"""Manual, bounded Klipper adjustments between prints.

This module is deliberately separate from the companion HTTP application.  It
does not start prints, pause a print, change temperatures, or persist Klipper
configuration.  A proposal is only a short-lived server-side capability: the
caller can confirm its opaque id, but cannot replace the values kept here.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


SAFE_PRINT_STATES = frozenset({"standby", "complete", "cancelled"})
PROPOSAL_TTL_SECONDS = 60
MAX_PROPOSALS = 128

_QUERY = "/printer/objects/query?webhooks&print_stats&extruder&toolhead&gcode_move&configfile"
_MAX_STEPS = {
    "pressure_advance": 0.005,
    "accel_mm_s2": 100.0,
    "extrusion_factor": 0.02,
}
_HARD_LO = {
    "pressure_advance": 0.0,
    "accel_mm_s2": 100.0,
    "extrusion_factor": 0.8,
}
_HARD_HI = {
    "pressure_advance": 0.2,
    "extrusion_factor": 1.2,
}
_PARAMETERS = frozenset({"pressure_advance", "accel_mm_s2", "extrusion_factor"})


class CalibrationControlError(ValueError):
    """Safe, user-facing failure from the manual calibration adapter."""


class CalibrationAuditError(CalibrationControlError):
    """The required local audit record could not be made durable."""


@dataclass
class _MachineSnapshot:
    webhooks_state: str
    print_state: str
    pressure_advance: float
    accel_mm_s2: float
    extrusion_factor: float
    config_max_accel: float

    def current(self, parameter: str) -> float:
        return {
            "pressure_advance": self.pressure_advance,
            "accel_mm_s2": self.accel_mm_s2,
            "extrusion_factor": self.extrusion_factor,
        }[parameter]

    def as_expected(self) -> dict[str, Any]:
        """Return only the finite, non-secret subset useful for a proposal."""
        return {
            "webhooks": {"state": self.webhooks_state},
            "print_stats": {"state": self.print_state},
            "extruder": {"pressure_advance": self.pressure_advance},
            "toolhead": {"max_accel": self.accel_mm_s2},
            "gcode_move": {"extrude_factor": self.extrusion_factor},
            "configfile": {"settings": {"printer": {"max_accel": self.config_max_accel}}},
        }


@dataclass
class _Proposal:
    proposal_id: str
    parameter: str
    current: float
    value: float
    bounds: tuple[float, float]
    maximum_step: float
    expected: dict[str, Any]
    config_max_accel: float
    expires_at: float
    state: str = "pending"
    applied_value: float | None = None


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationControlError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise CalibrationControlError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise CalibrationControlError(f"{field} must be a finite number")
    return result


def _parameter(parameter: Any) -> str:
    if not isinstance(parameter, str) or parameter not in _PARAMETERS:
        raise CalibrationControlError("Unsupported parameter")
    return parameter


def _bounds(bounds: Any, parameter: str, config_max_accel: float) -> tuple[float, float]:
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        raise CalibrationControlError("bounds must have the form [lo, hi]")
    lo = _number(bounds[0], "bounds[0]")
    hi = _number(bounds[1], "bounds[1]")
    if not lo < hi:
        raise CalibrationControlError("bounds requiere lo < hi")

    hard_lo = _HARD_LO[parameter]
    hard_hi = min(config_max_accel, 10_000.0) if parameter == "accel_mm_s2" else _HARD_HI[parameter]
    if hard_lo >= hard_hi or lo < hard_lo or hi > hard_hi:
        raise CalibrationControlError("bounds exceeds the permitted parameter limits")
    return lo, hi


def _step(maximum_step: Any, parameter: str) -> float:
    result = _number(maximum_step, "maximum_step")
    if result <= 0.0 or result > _MAX_STEPS[parameter]:
        raise CalibrationControlError("maximum_step excede el paso seguro permitido")
    return result


def _format_number(value: float) -> str:
    """Use a short decimal command without introducing binary artefacts."""
    return format(value, ".12g")


def _command(parameter: str, value: float) -> str:
    if parameter == "pressure_advance":
        return f"SET_PRESSURE_ADVANCE ADVANCE={_format_number(value)}"
    if parameter == "accel_mm_s2":
        return f"SET_VELOCITY_LIMIT ACCEL={_format_number(value)}"
        # value is already bounded to [0.8, 1.2], so this multiplication is finite.
    return f"M221 S{_format_number(value * 100.0)}"


def _same_value(left: float, right: float) -> bool:
    # Current-vs-proposal checks intentionally use equality, not a tolerance:
    # a later external change must not be silently overwritten.
    return left == right


class CalibrationController:
    """Create and manually apply one bounded, between-print adjustment at a time."""

    def __init__(self, moonraker_url: str, audit_path: str | os.PathLike[str], transport=None):
        if not isinstance(moonraker_url, str) or not moonraker_url.strip():
            raise CalibrationControlError("moonraker_url must be non-empty text")
        if audit_path is None:
            raise CalibrationControlError("audit_path es obligatorio")

        self._moonraker_url = moonraker_url.rstrip("/")
        self._audit_path = Path(audit_path)
        self._transport = transport
        self._proposals: dict[str, _Proposal] = {}
        self._lock = asyncio.Lock()

    async def preview(
        self,
        parameter: str,
        value: float,
        bounds,
        maximum_step: float,
    ) -> dict[str, Any]:
        """Validate a candidate against live state and return a short-lived proposal."""
        parameter = _parameter(parameter)
        target = _number(value, "value")
        maximum_step = _step(maximum_step, parameter)

        snapshot = await self._read_snapshot()
        limits = _bounds(bounds, parameter, snapshot.config_max_accel)
        current = snapshot.current(parameter)
        self._validate_machine_value(snapshot, parameter, current, "current")
        if not limits[0] <= current <= limits[1]:
            raise CalibrationControlError("current is outside bounds")
        if not limits[0] <= target <= limits[1]:
            raise CalibrationControlError("value is outside bounds")
        if abs(target - current) > maximum_step + 1e-12:
            raise CalibrationControlError("value supera maximum_step")
        if _same_value(target, current):
            raise CalibrationControlError("value must produce an actual adjustment")

        proposal_id = secrets.token_urlsafe(18)
        expected = snapshot.as_expected()
        record = _Proposal(
            proposal_id=proposal_id,
            parameter=parameter,
            current=current,
            value=target,
            bounds=limits,
            maximum_step=maximum_step,
            expected=expected,
            config_max_accel=snapshot.config_max_accel,
            expires_at=time.monotonic() + PROPOSAL_TTL_SECONDS,
        )

        async with self._lock:
            self._purge_proposals(time.monotonic())
            if len(self._proposals) >= MAX_PROPOSALS:
                raise CalibrationControlError("The stored proposal limit has been reached")
            self._proposals[proposal_id] = record

        return {
            "id": proposal_id,
            "parameter": parameter,
            "current": current,
            "value": target,
            "bounds": list(limits),
            "maximum_step": maximum_step,
            "expires_in_seconds": PROPOSAL_TTL_SECONDS,
            "expected": copy.deepcopy(expected),
            # Keep an explicit name for clients that prefer not to infer that
            # the expected object is a snapshot.
            "expected_snapshot": copy.deepcopy(expected),
            "validated_on_printer": False,
            "automatic_control": False,
        }

    async def apply(self, proposal_id: str, confirmed: bool) -> dict[str, Any]:
        """Apply a confirmed proposal once, then verify its live readback."""
        if confirmed is not True:
            raise CalibrationControlError("Applying a proposal requires confirmed=True")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise CalibrationControlError("Invalid proposal_id")

        async with self._lock:
            record = self._proposals.get(proposal_id)
            if record is None or record.state != "pending":
                raise CalibrationControlError(
                    "The proposal does not exist or has already been consumed"
                )
            if time.monotonic() >= record.expires_at:
                record.state = "expired"
                raise CalibrationControlError("The proposal has expired")

                # Consume the id before any await.  A failed precondition cannot be
                # turned into a later replay against a different machine state.
            record.state = "consumed"
            try:
                snapshot = await self._read_snapshot()
                self._validate_record(record, snapshot)
                if time.monotonic() >= record.expires_at:
                    raise CalibrationControlError("The proposal has expired")

                self._append_audit(
                    "attempted",
                    self._audit_fields(record, snapshot, operation="apply"),
                )
                if time.monotonic() >= record.expires_at:
                    raise CalibrationControlError("The proposal has expired")
            except CalibrationControlError:
                raise

            command = _command(record.parameter, record.value)
            try:
                await self._post_script(command)
            except CalibrationControlError as exc:
                record.state = "uncertain"
                self._audit_uncertain(record, operation="apply", reason="post_error")
                raise CalibrationControlError(
                    "The command may have been accepted; it will not be retried automatically"
                ) from exc

            try:
                readback = await self._read_snapshot()
                self._validate_applied_readback(record, readback)
            except CalibrationControlError as exc:
                record.state = "uncertain"
                self._audit_uncertain(record, operation="apply", reason="readback_error")
                raise CalibrationControlError(
                    "The adjustment could not be confirmed; its state is uncertain"
                ) from exc

            record.applied_value = readback.current(record.parameter)
            record.state = "applied"
            try:
                self._append_audit(
                    "applied",
                    self._audit_fields(record, readback, operation="apply"),
                )
            except CalibrationAuditError as exc:
                record.state = "uncertain"
                raise CalibrationControlError(
                    "The adjustment was read back, but its audit record is not durable"
                ) from exc
            return {
                "status": "applied",
                "proposal_id": record.proposal_id,
                "parameter": record.parameter,
                "previous": record.current,
                "value": record.value,
                "applied": record.applied_value,
                "readback": readback.as_expected(),
            }

    async def restore(self, proposal_id: str, confirmed: bool) -> dict[str, Any]:
        """Restore the pre-adjustment value once, without restarting Klipper."""
        if confirmed is not True:
            raise CalibrationControlError("Restoration requires confirmed=True")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise CalibrationControlError("Invalid proposal_id")

        async with self._lock:
            record = self._proposals.get(proposal_id)
            if record is None or record.state != "applied":
                raise CalibrationControlError("No applied adjustment is available to restore")

            snapshot = await self._read_snapshot()
            self._validate_restore(record, snapshot)
            self._append_audit(
                "attempted",
                self._audit_fields(record, snapshot, operation="restore", value=record.current),
            )

            command = _command(record.parameter, record.current)
            try:
                await self._post_script(command)
            except CalibrationControlError as exc:
                record.state = "uncertain"
                self._audit_uncertain(record, operation="restore", reason="post_error")
                raise CalibrationControlError(
                    "Restoration may have been accepted; it will not be retried"
                ) from exc

            try:
                readback = await self._read_snapshot()
                if not math.isclose(
                    readback.current(record.parameter),
                    record.current,
                    rel_tol=1e-6,
                    abs_tol=1e-6,
                ):
                    raise CalibrationControlError("Restoration does not match the readback")
            except CalibrationControlError as exc:
                record.state = "uncertain"
                self._audit_uncertain(record, operation="restore", reason="readback_error")
                raise CalibrationControlError(
                    "Restoration could not be confirmed; its state is uncertain"
                ) from exc

            record.state = "restored"
            try:
                self._append_audit(
                    "applied",
                    self._audit_fields(record, readback, operation="restore", value=record.current),
                )
            except CalibrationAuditError as exc:
                record.state = "uncertain"
                raise CalibrationControlError(
                    "Restoration was read back, but its audit record is not durable"
                ) from exc
            return {
                "status": "restored",
                "proposal_id": record.proposal_id,
                "parameter": record.parameter,
                "value": record.current,
                "readback": readback.as_expected(),
            }

    async def _read_snapshot(self) -> _MachineSnapshot:
        data = await self._request("GET", _QUERY)
        try:
            status = data["result"]["status"]
            if not isinstance(status, Mapping):
                raise CalibrationControlError("Invalid Moonraker response")
            webhooks = status["webhooks"]
            print_stats = status["print_stats"]
            extruder = status["extruder"]
            toolhead = status["toolhead"]
            gcode_move = status["gcode_move"]
            configfile = status["configfile"]
            settings = configfile["settings"]
            printer = settings["printer"]
            if not all(
                isinstance(item, Mapping)
                for item in (
                    webhooks,
                    print_stats,
                    extruder,
                    toolhead,
                    gcode_move,
                    configfile,
                    settings,
                    printer,
                )
            ):
                raise CalibrationControlError("Invalid Moonraker response")
            webhooks_state = webhooks["state"]
            print_state = print_stats["state"]
        except (KeyError, TypeError, AttributeError) as exc:
            raise CalibrationControlError("Invalid Moonraker response") from exc

        if not isinstance(webhooks_state, str) or webhooks_state != "ready":
            raise CalibrationControlError("The printer is not ready")
        if not isinstance(print_state, str) or print_state not in SAFE_PRINT_STATES:
            raise CalibrationControlError("The printer is not between prints")

        pressure_advance = _number(extruder.get("pressure_advance"), "extruder.pressure_advance")
        accel_mm_s2 = _number(toolhead.get("max_accel"), "toolhead.max_accel")
        extrusion_factor = _number(gcode_move.get("extrude_factor"), "gcode_move.extrude_factor")
        config_max_accel = _number(
            printer.get("max_accel"),
            "configfile.settings.printer.max_accel",
        )
        snapshot = _MachineSnapshot(
            webhooks_state=webhooks_state,
            print_state=print_state,
            pressure_advance=pressure_advance,
            accel_mm_s2=accel_mm_s2,
            extrusion_factor=extrusion_factor,
            config_max_accel=config_max_accel,
        )
        if config_max_accel <= 0.0:
            raise CalibrationControlError("The configured max_accel is invalid")
        self._validate_machine_value(snapshot, "pressure_advance", pressure_advance, "machine")
        self._validate_machine_value(snapshot, "accel_mm_s2", accel_mm_s2, "machine")
        self._validate_machine_value(snapshot, "extrusion_factor", extrusion_factor, "machine")
        return snapshot

    def _purge_proposals(self, now: float) -> None:
        """Release terminal records, retaining only pending or restorable ones."""
        removable = {
            proposal_id
            for proposal_id, record in self._proposals.items()
            if record.state in {"consumed", "expired", "uncertain", "restored"}
            or (record.state == "pending" and now >= record.expires_at)
        }
        for proposal_id in removable:
            del self._proposals[proposal_id]

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=5,
                trust_env=False,
                transport=self._transport,
            ) as client:
                options = {} if payload is None else {"json": payload}
                response = await client.request(method, self._moonraker_url + path, **options)
                response.raise_for_status()
                if not response.content:
                    return {}
                data = response.json()
        except CalibrationControlError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise CalibrationControlError("Unable to communicate with Moonraker") from exc
        if not isinstance(data, dict) or "error" in data:
            raise CalibrationControlError(
                "Moonraker rejected the request or returned an invalid response"
            )
        return data

    async def _post_script(self, command: str) -> None:
        # This is the only POST made by this module, and command construction
        # above has no path for temperatures, motion, SAVE_CONFIG, or shapers.
        await self._request("POST", "/printer/gcode/script", {"script": command})

    @staticmethod
    def _validate_machine_value(
        snapshot: _MachineSnapshot,
        parameter: str,
        value: float,
        field: str,
    ) -> None:
        hard_lo = _HARD_LO[parameter]
        hard_hi = (
            min(snapshot.config_max_accel, 10_000.0)
            if parameter == "accel_mm_s2"
            else _HARD_HI[parameter]
        )
        if hard_lo >= hard_hi or not math.isfinite(value) or not hard_lo <= value <= hard_hi:
            raise CalibrationControlError(f"{field} is outside the permitted limits")

    @classmethod
    def _validate_record(cls, record: _Proposal, snapshot: _MachineSnapshot) -> None:
        current = snapshot.current(record.parameter)
        cls._validate_machine_value(snapshot, record.parameter, current, "current")
        limits = _bounds(record.bounds, record.parameter, snapshot.config_max_accel)
        if limits != record.bounds:
            raise CalibrationControlError("The proposal bounds are no longer valid")
        if not _same_value(current, record.current):
            raise CalibrationControlError("The current value changed after preview")
        if not limits[0] <= record.value <= limits[1]:
            raise CalibrationControlError("value de la propuesta ya no es seguro")
        if abs(record.value - current) > record.maximum_step + 1e-12:
            raise CalibrationControlError("The proposal exceeds maximum_step")

    @classmethod
    def _validate_applied_readback(
        cls,
        record: _Proposal,
        snapshot: _MachineSnapshot,
    ) -> None:
        cls._validate_machine_value(
            snapshot,
            record.parameter,
            snapshot.current(record.parameter),
            "readback",
        )
        if not math.isclose(
            snapshot.current(record.parameter),
            record.value,
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise CalibrationControlError("Readback does not match the requested value")

    @classmethod
    def _validate_restore(cls, record: _Proposal, snapshot: _MachineSnapshot) -> None:
        cls._validate_machine_value(
            snapshot,
            record.parameter,
            snapshot.current(record.parameter),
            "current",
        )
        limits = _bounds(record.bounds, record.parameter, snapshot.config_max_accel)
        if limits != record.bounds:
            raise CalibrationControlError("The current bounds are no longer valid")
        if record.applied_value is None or not _same_value(
            snapshot.current(record.parameter), record.applied_value
        ):
            raise CalibrationControlError("The applied value was changed externally")
        if not limits[0] <= record.current <= limits[1]:
            raise CalibrationControlError(
                "The previous value is no longer within the permitted bounds"
            )

    @staticmethod
    def _audit_fields(
        record: _Proposal,
        snapshot: _MachineSnapshot,
        *,
        operation: str,
        value: float | None = None,
    ) -> dict[str, Any]:
        return {
            "proposal_id": record.proposal_id,
            "operation": operation,
            "parameter": record.parameter,
            "current": snapshot.current(record.parameter),
            "value": record.value if value is None else value,
            "print_state": snapshot.print_state,
        }

    def _audit_uncertain(self, record: _Proposal, *, operation: str, reason: str) -> None:
        try:
            self._append_audit(
                "uncertain",
                {
                    "proposal_id": record.proposal_id,
                    "operation": operation,
                    "parameter": record.parameter,
                    "value": record.value,
                    "reason": reason,
                },
            )
        except CalibrationAuditError:
            # The state remains non-reusable even if the secondary audit write
            # also fails; never turn an uncertain command into a retry.
            pass

    def _append_audit(self, event: str, fields: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        try:
            line = json.dumps(
                entry,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self._audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, TypeError, ValueError) as exc:
            raise CalibrationAuditError("The audit record could not be made durable") from exc


__all__ = ["CalibrationAuditError", "CalibrationControlError", "CalibrationController"]
