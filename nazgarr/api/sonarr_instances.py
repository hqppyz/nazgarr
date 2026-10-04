"""API di configurazione delle istanze Sonarr: il router comune di
nazgarr/api/arr_instances.py, con i nomi dei modelli dello schema OpenAPI
che il frontend usa (Schemas['SonarrInstance…'])."""

from nazgarr.api import arr_instances as arr
from nazgarr.models import SonarrInstance


# I nomi restano quelli di sempre nello schema OpenAPI (src/api/schema.ts).
class SonarrInstanceCreateRequest(arr.ArrInstanceCreateRequest):
    pass


class SonarrInstanceUpdateRequest(arr.ArrInstanceUpdateRequest):
    pass


class SonarrInstanceResponse(arr.ArrInstanceResponse):
    pass


class SonarrInstanceTestResponse(arr.ArrInstanceTestResponse):
    pass


class SonarrConnectionTestRequest(arr.ArrConnectionTestRequest):
    pass


router = arr.make_router(
    "sonarr", SonarrInstance,
    create_request=SonarrInstanceCreateRequest,
    update_request=SonarrInstanceUpdateRequest,
    response=SonarrInstanceResponse,
    test_response=SonarrInstanceTestResponse,
    connection_request=SonarrConnectionTestRequest,
)
