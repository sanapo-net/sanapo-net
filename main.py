# main.py
import asyncio

from core.kernel import Kernel

async def main():
    # core initialisation
    core = Kernel()
    print("the core is initialized")

    # module initialisation
    #print("modules are initialized")

    # module subscription
    #print("modules are subcribed")

    # start app
    await core.launch()
    print("the app is started")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("the app is stopped")