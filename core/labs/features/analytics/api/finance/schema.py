"""Document the finance permission's API-key alternative without changing auth."""

from django.conf import settings
from drf_spectacular.plumbing import ResolvedComponent

from config.schema import ProjectAutoSchema


class FinanceAutoSchema(ProjectAutoSchema):
    def get_auth(self) -> list[dict]:
        alternatives = super().get_auth()
        custom_header = getattr(settings, "API_KEY_CUSTOM_HEADER", None)
        header = custom_header.removeprefix("HTTP_").replace("_", "-") if custom_header else "Authorization"
        description = "Valid API key." if custom_header else "Use Authorization: Api-Key <key>."
        self.registry.register_on_missing(
            ResolvedComponent(
                name="financeApiKey",
                type=ResolvedComponent.SECURITY_SCHEMA,
                object=FinanceAutoSchema,
                schema={"type": "apiKey", "in": "header", "name": header, "description": description},
            )
        )
        return [*alternatives, {"financeApiKey": []}]
