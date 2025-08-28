from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew
from crewai.agents.agent_builder.base_agent import BaseAgent
from soinglobal_smartai.tools.telegram_dex_query_tool import TelegramDexQueryTool
from soinglobal_smartai.tools.enhanced_telegram_dex_tool import EnhancedTelegramDexTool
from typing import List
# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators


@CrewBase
class SoinglobalSmartai():
    """SoinglobalSmartai crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['researcher'],  # type: ignore[index]
            tools=[TelegramDexQueryTool(), EnhancedTelegramDexTool()],
            verbose=True
        )

    # Removed reporting_analyst agent

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    def chatbot_query_task(self, user_query: str) -> Task:
        self.tasks_config['chatbot_query_task']['description'] = user_query
        print(self.tasks_config['chatbot_query_task'])
        return Task(config=self.tasks_config['chatbot_query_task'])

    # Removed reporting_task

    @crew
    def crew(self, user_query: str) -> Crew:
        """Creates the SoinglobalSmartai crew"""
        return Crew(
            agents=[self.researcher()],
            tasks=[self.chatbot_query_task(user_query)],
            process=Process.sequential,
            verbose=True,
        )
