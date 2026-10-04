"""API di configurazione delle istanze Radarr: il router comune di
nazgarr/api/arr_instances.py, con i nomi dei modelli dello schema OpenAPI
che il frontend usa (Schemas['RadarrInstance…'])."""

from nazgarr.api import arr_instances as arr
from nazgarr.models import RadarrInstance


# I nomi restano quelli di sempre nello schema OpenAPI (src/api/schema.ts).
class RadarrInstanceCreateRequest(arr.ArrInstanceCreateRequest):
    pass


class RadarrInstanceUpdateRequest(arr.ArrInstanceUpdateRequest):
    pass


class RadarrInstanceResponse(arr.ArrInstanceResponse):
    pass


class RadarrInstanceTestResponse(arr.ArrInstanceTestResponse):
    pass


class RadarrConnectionTestRequest(arr.ArrConnectionTestRequest):
    pass


router = arr.make_router(
    "radarr", RadarrInstance,
    create_request=RadarrInstanceCreateRequest,
    update_request=RadarrInstanceUpdateRequest,
    response=RadarrInstanceResponse,
    test_response=RadarrInstanceTestResponse,
    connection_request=RadarrConnectionTestRequest,
)
