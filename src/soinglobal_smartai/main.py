#!/usr/bin/env python
import sys
import warnings

from datetime import datetime

from soinglobal_smartai.crew import SoinglobalSmartai

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information


def run():
    user_query = input("Enter your DEX/Telegram promoters query: ")
    crew_instance = SoinglobalSmartai()
    crew_instance.crew(user_query=user_query).kickoff()


if __name__ == "__main__":
    run()

