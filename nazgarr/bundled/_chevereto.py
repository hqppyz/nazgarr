"""Il pezzo comune dei plugin inclusi per gli host Chevereto: solo nazgarr.sdk,
come scriverebbe un plugin qualunque."""

from nazgarr.sdk import AdapterSpec, CheveretoImageHost, ConfigField, register

REQUIRES_SDK = ">=1.2,<2"


def register_chevereto(adapter_type: str, name: str, site: str) -> None:
    """Un host Chevereto: l'API sta in <site>/api/1/upload, la chiave nelle
    impostazioni dell'account (<site>/settings/api)."""
    endpoint = f"{site}/api/1/upload"
    register(AdapterSpec(
        "image_host", adapter_type, name,
        lambda ctx: CheveretoImageHost(ctx.config["api_key"], endpoint=endpoint, name=name),
        config_fields=(ConfigField("api_key", "API key", type="secret", required=True,
                                   help=f"From your account settings at {site}/settings/api."),),
        description=site,
    ))
