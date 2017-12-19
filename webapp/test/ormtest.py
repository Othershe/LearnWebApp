import asyncio

from webapp.www import orm
from webapp.www.config import configs
from webapp.www.models import User


async def save(loop):
    await orm.create_pool(loop=loop, **configs.db)
    # user = User(name='oscar', email='oscar@163.com', password='345678', image='about:blank')
    # await user.save()
    users = await User.find_all()
    print(users)


loop = asyncio.get_event_loop()
loop.run_until_complete(save(loop))
loop.close()
