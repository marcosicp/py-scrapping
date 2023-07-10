import asyncio
import greenlet
import random
import sys


class bridge:
    gl = None
    stop = object()

    @classmethod
    def get(cls):
        def gl_loop(coro):
            async def main():
                gl = greenlet.getcurrent().parent
                return await cls._run_gl(gl, coro)

            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())

        bridge_gl = greenlet.getcurrent().parent or cls.gl
        if not bridge_gl:
            bridge_gl = greenlet.greenlet(gl_loop)
            cls.gl = bridge_gl
        return bridge_gl

    @classmethod
    def stop(cls):
        if cls.gl:
            cls.gl.switch(cls.stop)

    @classmethod
    async def _run_gl(cls, gl, coro):
        while gl and coro != cls.stop:
            try:
                res = await coro
            except:
                gl.throw(*sys.exc_info())
            else:
                coro = gl.switch(res)
        return coro

def async_(f):
    async def wrapper(*args, **kwargs):
        gl = greenlet.greenlet(f)
        coro = gl.switch(*args, **kwargs)
        return await bridge._run_gl(gl, coro)
    return wrapper


def await_(task):
    bridge.get().switch(task)


def f():
    print('f')
    for i in range(3):
        await_(asyncio.sleep(random.random()))
        print(i)
    return 42


async def main():
    r = await async_(f)()
    print(r)


#asyncio.run(main())
#print(f())
