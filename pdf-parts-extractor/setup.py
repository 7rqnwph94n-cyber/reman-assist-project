from setuptools import setup, find_packages


setup(
    name="pdf-parts-extractor",
    version="0.1.0",
    description="PDF parts catalog extractor",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "pdfplumber",
        "pandas",
        "Pillow",
    ],
    entry_points={
        "console_scripts": [
            "pdf-parts-extract=pdf_parts_extractor.extract:main",
        ]
    },
)