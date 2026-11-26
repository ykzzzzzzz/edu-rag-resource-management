import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminDep, CurrentUserDep, DbDep
from app.errors import AppError, raise_for_unique_violation
from app.models import Course
from app.schemas import CourseCreate, CourseListOut, CourseOut, CourseUpdate

router = APIRouter(prefix="/courses", tags=["courses"])

COURSE_NAME_TAKEN = ("course_name_taken", "课程名称已存在")


@router.get("", response_model=CourseListOut)
def list_courses(db: DbDep, _user: CurrentUserDep) -> dict:
    courses = db.execute(select(Course).order_by(Course.name)).scalars().all()
    return {"items": [CourseOut.model_validate(c) for c in courses]}


@router.post("", status_code=201, response_model=CourseOut)
def create_course(body: CourseCreate, db: DbDep, _admin: AdminDep) -> Course:
    course = Course(name=body.name, description=body.description or None)
    db.add(course)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise_for_unique_violation(exc, *COURSE_NAME_TAKEN)
    db.refresh(course)
    return course


@router.patch("/{course_id}", response_model=CourseOut)
def update_course(course_id: uuid.UUID, body: CourseUpdate, db: DbDep, _admin: AdminDep) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise AppError(404, "course_not_found", "课程不存在")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "description":
            value = value or None
        setattr(course, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise_for_unique_violation(exc, *COURSE_NAME_TAKEN)
    db.refresh(course)
    return course
