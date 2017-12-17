import inspect
from urllib import parse

import os


def fn(a, b=5, *, c, d, **e):
    pass


params = inspect.signature(fn).parameters
print(params)
# OrderedDict([('a', <Parameter "a">), ('b', <Parameter "b=5">), ('c', <Parameter "c=10">)])
for name, param in params.items():
    print(param.kind)

d = parse.parse_qs('name=tom&age=18')
print(d)

# https://www.liaoxuefeng.com/discuss/001409195742008d822b26cf3de46aea14f2b7378a1ba91000/001462893855750f848630bb19c43c582fdff90f58cbee0000


s = os.path.abspath(__file__)
print(s)