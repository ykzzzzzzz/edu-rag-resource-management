from fastapi import APIRouter

from app.routers import admin_users, auth, courses, resources, system

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(system.router)
api_router.include_router(admin_users.router)
api_router.include_router(courses.router)
api_router.include_router(resources.router)
api_router.include_router(resources.admin_router)
