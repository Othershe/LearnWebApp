import asyncio

from webapp.www import orm
from webapp.www.models import User


async def save(loop):
    await orm.create_pool(loop=loop, user='root', password='123456', db='awesome')
    user = User(name='Othershe', email='othershe@163.com', password='123456', image='about:blank')
    await user.save()


loop = asyncio.get_event_loop()
loop.run_until_complete(save(loop))
loop.close()
