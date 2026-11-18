"""License-check staff endpoints (Labs staff policy; configuration changes are admin-only, D7)."""

from drf_api_contracts import OperationContract, ResponseContract

from core.common.api.api_views import AppListAPIView
from core.labs.features.base import CommandAPIView, operation

from ..application.manage import (
    CheckTarget,
    CreateLicenseCheckFromPresetInput,
    CreateLicenseCheckInput,
    UpdateLicenseCheckInput,
    create_license_check,
    create_license_check_from_preset,
    delete_license_check,
    update_license_check,
)
from ..presets import PRESETS
from ..queries.checks import get_license_check, latest_runs, list_license_checks, list_license_observations
from .serializers import (
    LicenseCheckPresetListSerializer,
    LicenseCheckQuerySerializer,
    LicenseCheckRunListSerializer,
    LicenseCheckSerializer,
    LicenseCheckWriteSerializer,
    LicenseObservationQuerySerializer,
    LicenseObservationSerializer,
)


def _targets(data) -> tuple[CheckTarget, ...] | None:
    if "targets" not in data:
        return None
    return tuple(CheckTarget(item["kind"], item["target_id"]) for item in data["targets"])


class _LicenseCheckAPIView(CommandAPIView):
    schema_tags = ("License checks",)

    def project_result(self, result):
        return get_license_check(check_id=result.pk)


class LicenseCheckListCreateAPIView(AppListAPIView, _LicenseCheckAPIView):
    """List license checks, or create one from scratch or from a preset (admins)."""

    get_contract = OperationContract(
        query=LicenseCheckQuerySerializer,
        success=ResponseContract.paginated("LicenseCheckList", LicenseCheckSerializer),
        bad_request=ResponseContract.problem(400),
    )
    post_contract = operation(
        "LicenseCheckCreate", LicenseCheckSerializer, request=LicenseCheckWriteSerializer, created=True, forbidden=True
    )

    def handle_get(self, request):
        params, error = self.validate_query()
        if error is not None:
            return error
        assert params is not None
        return self._execute(lambda: list_license_checks(q=params.get("q") or "", is_enabled=params.get("is_enabled")))

    def handle_post(self, request):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        data = serializer.validated_data
        targets = _targets(data) or ()
        if data.get("preset_key") and "probe" not in data:
            command = CreateLicenseCheckFromPresetInput(
                preset_key=data["preset_key"],
                key=data.get("key", ""),
                name=data.get("name", ""),
                is_enabled=data.get("is_enabled", True),
                is_lab_wide=data.get("is_lab_wide", False),
                targets=targets,
            )
            return self._execute(lambda: create_license_check_from_preset(command, actor=request.user), project=True)
        missing = [name for name in ("key", "name", "probe", "extract", "carrier") if name not in data]
        if missing:
            return self.respond_problem(
                self._validation_problem_name(),
                code="validation_failed",
                errors={name: ["This field is required."] for name in missing},
            )
        command = CreateLicenseCheckInput(
            key=data["key"],
            name=data["name"],
            vendor=data.get("vendor", ""),
            probe=data["probe"],
            extract=data["extract"],
            carrier=data["carrier"],
            interval_minutes=data.get("interval_minutes", 360),
            is_enabled=data.get("is_enabled", True),
            is_lab_wide=data.get("is_lab_wide", False),
            targets=targets,
            preset_key=data.get("preset_key", ""),
        )
        return self._execute(lambda: create_license_check(command, actor=request.user), project=True)


class LicenseCheckDetailAPIView(_LicenseCheckAPIView):
    """Read, change or delete one license check."""

    get_contract = operation("LicenseCheckDetail", LicenseCheckSerializer)
    patch_contract = operation(
        "LicenseCheckUpdate", LicenseCheckSerializer, request=LicenseCheckWriteSerializer, forbidden=True
    )
    delete_contract = operation(delete=True, forbidden=True)

    def handle_get(self, request, check_id, **kwargs):
        return self._execute(lambda: get_license_check(check_id=check_id))

    def handle_patch(self, request, check_id, **kwargs):
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        assert serializer is not None
        changes = {key: value for key, value in serializer.validated_data.items() if key not in {"key", "preset_key"}}
        targets = _targets(serializer.validated_data)
        if targets is not None:
            changes["targets"] = targets
        command = UpdateLicenseCheckInput(check_id, changes)
        return self._execute(lambda: update_license_check(command, actor=request.user), project=True)

    def handle_delete(self, request, check_id, **kwargs):
        return self._execute(lambda: delete_license_check(check_id=check_id, actor=request.user), delete=True)


class LicenseCheckPresetListAPIView(_LicenseCheckAPIView):
    """Templates for new checks (for example the Vector License Client)."""

    get_contract = OperationContract(
        success=ResponseContract.success("LicenseCheckPresetList", LicenseCheckPresetListSerializer)
    )

    def handle_get(self, request):
        return self._execute(lambda: {"items": list(PRESETS.values())})


class LicenseCheckRunListAPIView(_LicenseCheckAPIView):
    """The newest run of a check on each computer it reached."""

    get_contract = OperationContract(
        success=ResponseContract.success("LicenseCheckRunList", LicenseCheckRunListSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request, check_id, **kwargs):
        return self._execute(lambda: {"items": latest_runs(check_id=check_id)})


class LicenseObservationListAPIView(AppListAPIView, _LicenseCheckAPIView):
    """Licenses agents found on lab computers and their hardware, with the match to the inventory."""

    get_contract = OperationContract(
        query=LicenseObservationQuerySerializer,
        success=ResponseContract.paginated("LicenseObservationList", LicenseObservationSerializer),
        bad_request=ResponseContract.problem(400),
    )

    def handle_get(self, request):
        params, error = self.validate_query()
        if error is not None:
            return error
        assert params is not None
        filters = {
            name: params[name] for name in ("status", "check_id", "license_id", "computing_id") if params.get(name)
        }
        return self._execute(
            lambda: list_license_observations(
                **filters,
                needs_attention=params.get("is_attention_required"),
                include_removed=bool(params.get("include_removed")),
                q=params.get("q") or "",
            )
        )
