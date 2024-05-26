import openpyxl
import csv
import json
from typing import List, Optional, Tuple


class GlossaryTermsSaver:
    """
    Saves term definitions from the glossary to a file based on the file extension.

    To add support for saving to a new file extension, create a subclass and add a new static method to the class with the name
    `save_as_<file_extension>`.
    The method should take in the following parameters:
        - topic: The topic on which the terms are based
        - results: The results to save
        - filename: The name of the file to save the results in. Can also be the path to the file
    The method should also return None

    For example:
    ```python
    class CustomSaver(GlossaryTermsSaver):
        @staticmethod
        def save_as_<file_ext>(topic: str, results: List[Tuple[str, str]], filename: Optional[str] = None):
            filename = f'{topic.title()} Glossary.<file_extension>' if filename is None else filename
            # Do something
            return None

    saver = CustomSaver()
    saver.save('topic', [('term', 'definition')], 'pathtofile/filename.<file_ext>')
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

    def save(self, topic: str, results: List[Tuple[str, str]], filename: Optional[str] = None) -> bool:
        """
        Save the given results to a file based on the file extension of the given filename
        if no filename is given, the results will be saved to a text file with the name "<topic> Glossary.txt"

        :param topic: The topic on which the results are based
        :param results: The results to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        :return: True if the results were saved successfully, False otherwise
        :raises: NotImplementedError if the file extension of the given filename is not supported
        """
        file_extension = filename.split('.')[-1] if filename else 'txt'
        try:
            getattr(self, f'save_as_{file_extension}')(topic, results, filename)
            return True
        except AttributeError:
            raise NotImplementedError(
                f'Cannot save to {file_extension} files. `save_as_{file_extension}` method not implemented'
            )
        except Exception:
            return False
    

    @staticmethod
    def save_as_xlsx(topic: str, results: List[Tuple[str, str]], filename: Optional[str] = None) -> None:
        """
        Save the given results as an excel file

        :param topic: The topic on which the results are based
        :param results: The results to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.xlsx'):
            raise ValueError('Invalid file name. File name must end with .xlsx')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = topic.title()
        ws.append(['Term', 'Definition'])
        for result in results:
            ws.append(result)
        filename = f'{topic.title()} Glossary.xlsx' if filename is None else filename
        wb.save(filename)
        wb.close()
        return None
    

    @staticmethod
    def save_as_csv(topic: str, results: List[Tuple[str, str]], filename: Optional[str] = None) -> None:
        """
        Save the given results as a csv file

        :param topic: The topic on which the results are based
        :param results: The results to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.csv'):
            raise ValueError('Invalid file name. File name must end with .csv')
        filename = f'{topic.title()} Glossary.csv' if filename is None else filename
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(['Term', 'Definition'])
            f.write('\n')
            for result in results:
                writer.writerow(result)
                f.write('\n')
        return None
    

    @staticmethod
    def save_as_json(topic: str, results: List[Tuple[str, str]], filename: Optional[str] = None):
        """
        Save the given results as a json file

        :param topic: The topic on which the results are based
        :param results: The results to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.json'):
            raise ValueError('Invalid file name. File name must end with .json')
        filename = f'{topic.title()} Glossary.json' if filename is None else filename
        with open (filename, 'w') as f:
            d = {}
            for result in results:
                d[result[0]] = result[1]
            json.dump(d, f, indent=4)
        return None
    

    @staticmethod
    def save_as_txt(topic: str, results: List[Tuple[str, str]], filename: Optional[str] = None):
        """
        Save the given results as a text file

        :param topic: The topic on which the results are based
        :param results: The results to save
        :param filename: The name of the file to save the results in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.txt'):
            raise ValueError('Invalid file name. File name must end with .txt')
        filename = f"{topic.title()} Glossary.txt" if filename is None else filename
        with open(filename, 'w') as f:
            for i, result in enumerate(results, start=1):
                f.write(f"({i}). {result[0].title()}:\n{result[1]}\n\n")
        return None
