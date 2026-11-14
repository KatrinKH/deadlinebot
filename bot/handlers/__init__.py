from aiogram import Router

from bot.handlers import add, change_requests, common, deadlines, start, subjects


def get_root_router() -> Router:
    router = Router(name="root")
    router.include_routers(
        start.router,
        subjects.router,
        change_requests.router,
        add.router,
        deadlines.router,
        common.router,  # последним: содержит fallback для любых сообщений
    )
    return router
