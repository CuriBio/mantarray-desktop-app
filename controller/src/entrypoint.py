# -*- coding: utf-8 -*-
import asyncio
import sys

import controller

if __name__ == "__main__":
    asyncio.run(controller.main.main(sys.argv[1:]))
