"""Lensdump screenshots for Nazgarr: an example image host plugin (docs/SDK.md).

Lensdump's API needs a paid account, so it is not included in Nazgarr.
Install it by adding the package to NAZGARR_PLUGINS (or plugins.txt in the
data folder), for example from a git checkout:

    NAZGARR_PLUGINS="git+https://github.com/lktorrentz/nazgarr#subdirectory=examples/nazgarr-lensdump"

then set its API key in Settings > Upload > Image hosts, where it joins the
priority list. Lensdump runs Chevereto, so the whole plugin is one
CheveretoImageHost: any other Chevereto host is written the same way.
"""

import nazgarr.sdk as sdk

# CheveretoImageHost arrived in SDK 1.2.
REQUIRES_SDK = ">=1.2,<2"


def setup() -> None:
    sdk.register(sdk.AdapterSpec(
        "image_host", "lensdump", "Lensdump",
        lambda ctx: sdk.CheveretoImageHost(
            ctx.config["api_key"], endpoint="https://lensdump.com/api/1/upload", name="Lensdump",
        ),
        config_fields=(
            sdk.ConfigField("api_key", "API key", type="secret", required=True,
                            help="Paid accounts only: lensdump.com, account settings, API."),
        ),
        description="https://lensdump.com (paid API)",
    ))
