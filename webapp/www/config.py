"""
读取统一的配置文件
"""

from webapp.www import config_default, config_override


class Dict(dict):
    """
    扩展dict，实现可通过d.key调用的功能
    """

    def __init__(self, names=(), values=(), **kw):
        super(Dict, self).__init__(**kw)
        for k, v in zip(names, values):
            self[k] = v

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError("'Dict' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value


def merge(default, override):
    """
    合并两个dict类型的config文件，override会覆盖default
    """
    r = {}
    for k, v in default.items():
        if k in override:
            if isinstance(v, dict):
                r[k] = merge(v, override[k])
            else:
                r[k] = override[k]
        else:
            r[k] = v
    return r


def to_dict(d):
    """
    将一个普通的dict转成我们自定义的Dict
    """
    md = Dict()
    for k, v in d.items():
        md[k] = to_dict(v) if isinstance(v, dict) else v
    return md


configs = merge(config_default.configs, config_override.configs)
configs = to_dict(configs)
