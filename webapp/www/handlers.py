from webapp.www.coroweb import get
from webapp.www.models import User


@get('/')
async def index(request):
    users = await User.find_all()
    return {
        # 指定模板名
        '__template__': 'test.html',
        'users': users
    }


@get('/main')
async def main(request):
    return '<h1>Main Page</h1>'
