import os
import csv
import json
import sys
from typing import List, TypeVar

from .glossary import SearchResult



class Saver(object):
    """
    Saves term definitions from the glossary to a file based on the file extension.

    To add support for saving to a new file extension, create a subclass and add a new static method to the class with the name
    `save_as_<file_extension>`.
    The method should take in the following parameters:
        - results: A list of SearchResult to save
        - filename: The name of the file to save the results in. Can also be the path to the file
    The method should also return None

    Default supported file extensions are xlsx, csv, json and txt.

    For Example:
    ```python
    class CustomSaver(Saver):
        @staticmethod
        def save_as_<file_ext>(results: List[SearchResult], filename: str):
            # Save implementation
            return None

    saver = CustomSaver()
    saver.save([SearchResult, ...], 'pathtofile/filename.<file_ext>')
    ```
    """
    @property
    def supported_file_types(self) -> List[str]:
        """
        A list of file extensions that the class supports saving to
        by default the class supports saving to xlsx, csv, json and txt files.
        """
        available_savers = [method for method in dir(self) if method.startswith('save_as_')]
        return [saver.split('_')[-1] for saver in available_savers]

    def save(self, results: List[SearchResult], filename: str) -> None:
        """
        Save the given results to a file based on the file extension of the given filename

        :param results: The results to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        :raises: NotImplementedError if the file extension of the given filename is not supported
        """
        file_extension = filename.split('.')[-1] if filename else 'txt'
        try:
            return getattr(self, f'save_as_{file_extension}')(results, filename)
        except AttributeError:
            raise NotImplementedError(
                f'Cannot save to {file_extension} files. `save_as_{file_extension}` method not implemented'
            )
    

    @staticmethod
    def save_as_xlsx(results: List[SearchResult], filename: str) -> None:
        """
        Save the given results in an excel file.

        You need to have openpyxl installed to save to xlsx files. Run `pip install openpyxl` to install it

        :param results: List of SearchResult to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        """
        try:
            import openpyxl
        except ImportError:
            raise ImportError(
                '"openpyxl" is required to save to xlsx files. Run `pip install openpyxl` in yut terminal to install it'
            )
        
        name, ext = os.path.splitext(filename)
        if not ext.lower() == '.xlsx':
            raise ValueError('Invalid file name. File name must end with .xlsx')
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = name.title()
        ws.append(('Term', 'Definition', 'Grammatical Label', 'Topic')) # Add a header row
        for result in results:
            ws.append(result.astuple())
        
        wb.save(filename)
        wb.close()
        return None
    

    @staticmethod
    def save_as_csv(results: List[SearchResult], filename: str) -> None:
        """
        Save the given results as a csv file

        :param results: A list of SearchResult to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        """
        name, ext = os.path.splitext(filename)
        if not ext.lower() == '.csv':
            raise ValueError('Invalid file name. File name must end with .csv')
        
        with open(filename, 'w', newline='\n') as file:
            writer = csv.writer(file, delimiter=', ', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow((name.title(),)) # Add a title row
            file.write('\n')
            writer.writerow(('Term', 'Definition', 'Grammatical Label', 'Topic')) # Add a header row
            file.write('\n')
            for result in results:
                writer.writerow(result.astuple())
        return None
    

    @staticmethod
    def save_as_json(results: List[SearchResult], filename: str) -> None:
        """
        Save the given results as a json file

        :param results: A list of SearchResult to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        """
        _, ext = os.path.splitext(filename)
        if not ext.lower() == '.json':
            raise ValueError('Invalid file name. File name must end with .json')
        
        with open (filename, 'w') as file:
            _dict = {}
            for result in results:
                result_dict = result.asdict()
                _dict[result_dict.pop('term')] = result_dict
            json.dump(_dict, file, indent=4)
        return None
    

    @staticmethod
    def save_as_txt(results: List[SearchResult], filename: str) -> None:
        """
        Save the given results as a text file

        :param results: A list of SearchResult to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        """
        name, ext = os.path.splitext(filename)
        if not ext.lower() == '.txt':
            raise ValueError('Invalid file name. File name must end with .txt')
        
        with open(filename, 'w') as file:
            file.write(f'{name.title()}\n\n') # Add a title
            for i, result in enumerate(results, start=1):
                file.write(
                    f"({i}). {result.term} ({result.topic or ""}) - {result.grammatical_label}:\n"
                    f"{result.definition or ""}\r\n"
                )
        return None


_Saver = TypeVar("_Saver", bound=Saver)
