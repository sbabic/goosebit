from fastapi.requests import Request
from pydantic import BaseModel, Field

from goosebit.schema.rollouts import RolloutSchema


class BFFRolloutsResponse(BaseModel):
    data: list[RolloutSchema]
    draw: int
    records_total: int = Field(serialization_alias="recordsTotal")
    records_filtered: int = Field(serialization_alias="recordsFiltered")

    @classmethod
    async def convert(cls, request: Request, query, search_filter, total_records):
        params = request.query_params

        draw = int(params.get("draw", 1))
        start = int(params.get("start", 0))
        length = int(params.get("length", 10))
        search_value = params.get("search[value]", None)
        order_column_index = params.get("order[0][column]", None)
        order_column = params.get(f"columns[{order_column_index}][data]", None)
        order_dir = params.get("order[0][dir]", None)

        if search_value:
            query = query.filter(search_filter(search_value))

        if order_column:
            query = query.order_by(f"{'-' if order_dir == 'desc' else ''}{order_column}")

        filtered_records = await query.count()
        rollouts = await query.offset(start).limit(length).all()
        data = [RolloutSchema.model_validate(r) for r in rollouts]

        return cls(data=data, draw=draw, records_total=total_records, records_filtered=filtered_records)
