from aiohttp import web

async def handle(request):
    return web.Response(text="Bot is alive!")

def start_keep_alive():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)

    async def start():
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8080)
        await site.start()

    import asyncio
    asyncio.get_event_loop().create_task(start())
