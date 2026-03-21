from setuptools import setup, find_packages

setup(
    name="mem0-agent-setup",
    version="0.1.0",
    description="为 AI Agent 配置 Mem0 向量记忆系统",
    author="Your Name",
    author_email="your@email.com",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "mem0ai>=0.1.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "mem0-agent=bin.mem0_agent:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
