from setuptools import setup, find_packages

setup(
    name='slb_glossary_finder',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'selenium>=4.10.0',
        'openpyxl>=3.1.2',
    ],
    entry_points={
        'console_scripts': [
            'slb_glossary_finder = slb_glossary_finder.slb_glossary_finder:main',
        ],
    },
)

