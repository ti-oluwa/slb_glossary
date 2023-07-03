"""Contains class for saving glossary terms to a file"""

import openpyxl
import csv
import json
from typing import List, Tuple


class GlossaryTermsSaver:
    """
    A class that saves glossary terms to a file

    :attr supported_file_extensions: A list of file extensions that the class supports saving to
    by default the class supports saving to xlsx, csv, json and txt files.
    To add support for saving to a new file extension, create a subclass and add a new static method to the class with the name
    `save_as_<file_extension>`.
    The method should take in the following parameters:
        - topic: The topic on which the terms are based
        - terms: The terms to save
        - filename: The name of the file to save the terms in. Can also be the path to the file
    The method should also return None

    For example:
    >>> class MySaver(GlossaryTermsSaver):
            @staticmethod
            def save_as_<file_extension>(topic: str, terms: List[Tuple[str, str]], filename: str = None):
                filename = f'{topic.title()} Glossary.<file_extension>' if filename is None else filename
                # Do something
                return None

    >>> my_saver = MySaver()
    >>> my_saver.save('topic', [('term', 'definition')], 'pathtofile/filename.<file_extension>')
    """

    @property
    def supported_file_extensions(self):
        available_savers = [method for method in dir(self) if method.startswith('save_as_')]
        return [saver.split('_')[-1] for saver in available_savers]

    def save(self, topic: str, terms: List[Tuple[str, str]], filename: str = None):
        """
        Save the given terms to a file based on the file extension of the given filename
        if no filename is given, the terms will be saved to a text file with the name "<topic> Glossary.txt"

        :param topic: The topic on which the terms are based
        :param terms: The terms to save
        :param filename: The name of the file to save the terms in. Can also be the path to the file
        :return: None
        """
        file_extension = filename.split('.')[-1] if filename else 'txt'
        try:
            return getattr(self, f'save_as_{file_extension}')(topic, terms, filename)
        except AttributeError:
            raise NotImplementedError(f'Cannot save to {file_extension} files. `save_as_{file_extension}` method not implemented')

    @staticmethod
    def save_as_xlsx(topic: str, terms: List[Tuple[str, str]], filename: str = None):
        """
        Save the given terms as an excel file

        :param topic: The topic on which the terms are based
        :param terms: The terms to save
        :param filename: The name of the file to save the terms in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.xlsx'):
            raise ValueError('Invalid file name. File name must end with .xlsx')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = topic.title()
        ws.append(['Term', 'Definition'])
        for term in terms:
            ws.append(term)
        filename = f'{topic.title()} Glossary.xlsx' if filename is None else filename
        wb.save(filename)
        wb.close()
        return None

    @staticmethod
    def save_as_csv(topic: str, terms: List[Tuple[str, str]], filename: str = None):
        """
        Save the given terms as a csv file

        :param topic: The topic on which the terms are based
        :param terms: The terms to save
        :param filename: The name of the file to save the terms in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.csv'):
            raise ValueError('Invalid file name. File name must end with .csv')
        filename = f'{topic.title()} Glossary.csv' if filename is None else filename
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(['Term', 'Definition'])
            f.write('\n')
            for term in terms:
                writer.writerow(term)
                f.write('\n')
        return None

    @staticmethod
    def save_as_json(topic: str, terms: List[Tuple[str, str]], filename: str = None):
        """
        Save the given terms as a json file

        :param topic: The topic on which the terms are based
        :param terms: The terms to save
        :param filename: The name of the file to save the terms in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.json'):
            raise ValueError('Invalid file name. File name must end with .json')
        filename = f'{topic.title()} Glossary.json' if filename is None else filename
        with open (filename, 'w') as f:
            d = {}
            for term in terms:
                d[term[0]] = term[1]
            json.dump(d, f, indent=4)
        return None

    @staticmethod
    def save_as_txt(topic: str, terms: List[Tuple[str, str]], filename: str = None):
        """
        Save the given terms as a text file

        :param topic: The topic on which the terms are based
        :param terms: The terms to save
        :param filename: The name of the file to save the terms in. Can also be the path to the file
        :return: None
        """
        if filename and not filename.endswith('.txt'):
            raise ValueError('Invalid file name. File name must end with .txt')
        filename = f"{topic.title()} Glossary.txt" if filename is None else filename
        with open(filename, 'w') as f:
            for i, term in enumerate(terms, start=1):
                f.write(f"({i}). {term[0].title()}:\n{term[1]}\n\n")
        return None
