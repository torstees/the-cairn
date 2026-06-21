from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    ProgressStatus,
    StudentProgress,
    Tune,
    TuneBox,
)
from cairn.services.boxes import list_boxes
from cairn.services.lists import get_active_list

_LEARNING_STATUSES = {
    ProgressStatus.just_learning,
    ProgressStatus.getting_there,
    ProgressStatus.nearly_there,
    ProgressStatus.session_ready,
}

_RETENTION_STATUSES = {
    ProgressStatus.committed,
    ProgressStatus.performance_ready,
    ProgressStatus.solo_ready,
}


@dataclass
class TuneRow:
    tune: Tune
    progress: StudentProgress


@dataclass
class DashboardData:
    active_box: TuneBox | None
    active_list_name: str | None
    active_list_type_label: str | None
    due_retention: list[TuneRow]
    learning: list[TuneRow]


async def get_dashboard_data(db: AsyncSession, user_id: int) -> DashboardData:
    active_list = await get_active_list(db, user_id)
    boxes = await list_boxes(db, user_id)

    box_id: int | None = None
    active_box: TuneBox | None = None

    if active_list:
        box_id = active_list.box_id
        active_box = next((b for b in boxes if b.id == box_id), None)
    elif boxes:
        active_box = boxes[0]
        box_id = active_box.id

    active_list_name = active_list.name if active_list else None
    active_list_type_label = active_list.list_type.label if active_list else None

    if box_id is None:
        return DashboardData(
            active_box=None,
            active_list_name=active_list_name,
            active_list_type_label=active_list_type_label,
            due_retention=[],
            learning=[],
        )

    now = datetime.now(UTC)

    progress_result = await db.execute(
        select(StudentProgress, Tune)
        .join(Tune, StudentProgress.tune_id == Tune.id)
        .where(
            StudentProgress.user_id == user_id,
            StudentProgress.box_id == box_id,
        )
        .order_by(StudentProgress.next_suggested, Tune.sort_title)
    )
    rows = progress_result.all()

    now_naive = now.replace(tzinfo=None)
    due_retention: list[TuneRow] = []
    learning: list[TuneRow] = []

    for sp, tune in rows:
        if sp.status in _RETENTION_STATUSES:
            next_sug = sp.next_suggested
            if next_sug is None or next_sug.replace(tzinfo=None) <= now_naive:
                due_retention.append(TuneRow(tune=tune, progress=sp))
        elif sp.status in _LEARNING_STATUSES:
            learning.append(TuneRow(tune=tune, progress=sp))

    learning.sort(key=lambda r: (list(ProgressStatus).index(r.progress.status), r.tune.sort_title))

    return DashboardData(
        active_box=active_box,
        active_list_name=active_list_name,
        active_list_type_label=active_list_type_label,
        due_retention=due_retention,
        learning=learning,
    )
