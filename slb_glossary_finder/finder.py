"""Contains class for finding glossary terms in the SLB glossary."""

from typing import Tuple, List
from selenium import webdriver
from selenium.webdriver.common.by import By
import math
import time
from selenium.webdriver.wpewebkit.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.safari.options import Options as SafariOptions

from .save import GlossaryTermsSaver
from .exceptions import NetworkError, BrowserException, BrowserNotInstalled, BrowserNotSupported


ALLOWED_BROWSERS = webdriver.__all__
base_search_url = 'https://glossary.slb.com/en/search'


class SLBGlossaryTermsFinder:
    """
    Class for finding terms in the SLB glossary using Selenium
    
    :attr wait_duration: The number of seconds to wait for an element to be found before throwing an error

    :attr browser: The browser webdriver instance to be used in finding the terms

    :attr saver: The GlosssaryTermsSaver object to be used in saving the terms found
    """

    wait_duration = 5
    saver = GlossaryTermsSaver()

    def __init__(self, browser: str ='chrome', **kwargs) -> None:
        """
        Initialize the glossary terms finder

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param kwargs: Other keyword arguments
                :kwargs page_load_timeout: The number of seconds to wait for a page to load before throwing an error

                :kwargs wait_duration: The number of seconds to wait for an element to be found before throwing an error

                :kwargs open_browser_window: Whether to open the browser window or not. Defaults to False
        """ 
        return self._init_browser(browser, **kwargs)
        

    def _init_browser(self, browser: str, **kwargs) -> None:
        """
        Initialize the browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param kwargs: Other keyword arguments
                :kwargs page_load_timeout: The number of seconds to wait for a page to load before throwing an error

                :kwargs wait_duration: The number of seconds to wait for an element to be found before throwing an error

                :kwargs open_browser_window: Whether to open the browser window or not. Defaults to False
        """
        browser = browser.title().replace(' ', '')
        if browser not in ALLOWED_BROWSERS:
            raise BrowserNotSupported(f'{browser.title()} is not supported by selenium')

        options = self._get_headless_options(browser) if kwargs.get('open_browser_window', False) is False else None
        try:
            self.browser: WebDriver = getattr(webdriver, browser)(options=options)
        except AttributeError:
            raise BrowserNotInstalled(f'{browser.title()} is not installed on your machine')

        if kwargs.get('page_load_timeout', None):
            self.browser.set_page_load_timeout(kwargs.get('page_load_timeout'))
        if kwargs.get('wait_duration', None):
            self.wait_duration = kwargs.get('wait_duration')
            
        self.browser.implicitly_wait(self.wait_duration)


    def _get_headless_options(self, browser: str):
        """
        Get the browser options for the given browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        :return: The browser options for the given browser in headless mode
        """
        options = None
        match browser.lower():
            case 'chrome':
                options = webdriver.ChromeOptions()
                options.add_argument('--headless')
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
            case 'firefox':
                options = webdriver.FirefoxOptions()
                options.headless = True
            case 'edge':
                options = webdriver.EdgeOptions()
                options.add_argument('--headless')
            case 'chromiumedge':
                options = webdriver.EdgeOptions()
                options.use_chromium = True
                options.add_argument('--headless')
            case 'safari':
                options = SafariOptions()
                # Enable automatic handling of the WebDriver extension
                options.set_capability("safari:automaticInspection", True)
                options.set_capability("safari:automaticProfiling", True)
                # Set headless mode by hiding the browser window
                options.add_argument("-background")
        return options

    
    def _load(self, url):
        """
        Load the given url in the browser

        :param url: The url to load
        """
        try:
            self.browser.get(url)
        except WebDriverException as e:
            raise NetworkError(e)
        except Exception as e:
            raise BrowserException(e)


    @staticmethod
    def get_pager_query(no_of_terms_per_tab: int = 12, tab_number: int = 1):
        """
        Get the query string for the pager/paginator that will be used to get the terms on the given tab

        :param no_of_terms_per_tab: The number of terms per tab
        :param tab_number: The tab number to get the query string for
        :return: The query string for the pager/paginator that will be used to get the terms on the given tab
        """
        if tab_number < 2:
            return ''
        return f'first={no_of_terms_per_tab * (tab_number - 1)}&'


    @staticmethod
    def generate_slb_url(topic: str, query: str = None, pager_query: str = None, start_letter: str = None):
        """
        Generate the url for the given parameters

        :param topic: The topic to get the terms for
        :param query: The search query to use
        :param pager_query: The query string for the pager/paginator that will be used to get the terms on the given tab
        :param start_letter: The first letter of the terms to get
        :return: The url for the given parameters
        """
        if not topic and not(query or start_letter):
            return base_search_url
        if query:
            query = f"q={query}&"
        if start_letter:
            start_letter = f"&f:TermStartLetterFacet=[{start_letter[0].upper()}]"
        if topic:
            topic = f"&f:DisciplineFacet=[{topic.strip().title()}]"
        return f"{base_search_url}#{query or ''}{pager_query or ''}sort=relevancy{topic or ''}{start_letter or ''}"
        

    def get_terms_urls(self, topic: str, query: str = None, start_letter: str = None, count: int = None, **kwargs):
        """
        Get the urls of the terms under the given topic

        :param topic: The topic to get the terms for
        :param query: The search query to use
        :param start_letter: The first letter of the terms to get
        :param count: The number of terms to get. If None, all term urls will be returned
        :param kwargs: Other keyword arguments
        :return: A list of urls of the terms under the given topic
        """
        if count and count < 1:
            raise ValueError('Count must be greater than 0')

        pager_query = self.get_pager_query(tab_number=kwargs.get('tab', 1))
        urls = kwargs.get('urls', [])
        if urls:
            old_page_source = self.browser.page_source

        url = self.generate_slb_url(topic=topic, query=query, pager_query=pager_query, start_letter=start_letter)
        self._load(url)

        if urls:
            # If we're moving to a new tab, ensure page content as changed completely before proceeding to get new urls
            updated_page_source = self.browser.page_source
            while old_page_source == updated_page_source:
                time.sleep(3)

        results_header = self.browser.find_element(by=By.CLASS_NAME, value='coveo-results-header')
        # if result header has content, results have been loaded else reload page
        while results_header.text == '':
            print('Content not loaded yet. Reloading page...')
            return self.get_terms_urls(topic, query=query, start_letter=start_letter, count=count, **kwargs)

        try:
            total_no_of_terms_found = int(self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoQuerySummary .coveo-highlight')[2].text.replace(',', ''))
        except IndexError:
            print(f"Could not get total number of terms found on tab {kwargs.get('tab', 1)}. Returning urls found so far...")
            # If for any reason the total number of terms found is not found, return term urls found so far
            return urls

        found_terms = self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink')
        no_of_terms_per_tab = len(found_terms)
        max_no_of_tabs = math.ceil(total_no_of_terms_found / no_of_terms_per_tab)
        count = total_no_of_terms_found if count is None else count
        # Get term detail urls on tab
        urls.extend([ term.get_attribute('href') for term in found_terms[:count] ])
        count -= no_of_terms_per_tab
    
        if count > 0:   # if there are more terms to find
            current_tab = kwargs.get('tab', 1)
            next_tab = current_tab + 1
            if next_tab <= max_no_of_tabs:
                return self.get_terms_urls(topic, query=query, start_letter=start_letter, count=count, tab=next_tab, urls=urls)
        return urls


    def get_term_details(self, topic: str, term_url: str):
        """
        Get the details of the term on the given url

        :param topic: The topic to base the search on
        :param term_url: The url of the term to get the details for
        :return: A tuple containing the term name and its definition
        """
        self._load(term_url)
        term_name: str = self.browser.find_element(by=By.CSS_SELECTOR, value=".row .small-12 h1 strong").text
        term_details = self.browser.find_elements(by=By.CSS_SELECTOR, value='.content-two-col__text')
        details = []

        for detail in term_details:
            sub_details = detail.find_elements(by=By.CSS_SELECTOR, value='p')
            term_definition_sub: str = sub_details[0].text
            term_definition: str = sub_details[2].text if sub_details[1].text == "" else sub_details[1].text

            if topic and topic.lower() in term_definition_sub.lower():
                details.append((term_name, term_definition))
                return details
            elif topic == "":
                details.append((term_name, f"Under {term_definition_sub.split('.')[-1].strip()} - {term_definition}"))

        if details == []:
            details.append((term_name, ""))
        return details


    def find_terms_on(self, topic: str, max_results: int = None) -> List[Tuple[str, str]]:
        """
        Find terms on a given topic in the glossary

        :param topic: The topic to base the search on
        :param max_results: The maximum number of terms to find. If None, all terms will be returned
        :return: A list of tuples containing the terms under the given topic and their definitions

        Note this method returns only the definitions of the terms related to the given topic. 
        If you want to get all the definitions of the terms, use `search` instead.
        """
        term_links = self.get_terms_urls(topic, count=max_results)
        return [ self.get_term_details(topic, term_link)[0] for term_link in term_links ]


    def search(self, query: str, topic: str = None, start_letter: str = None, max_results: int = 3):
        """
        Search the glossary for terms matching the given query and other filters

        :param query: The query to search for
        :param topic: filter the search under the given topic
        :param start_letter: filter the search to terms starting with the given letter
        :param max_results: The maximum number of results to return. Defaults to 3. If None, all results will be returned
        :return: A list of containing the details on the first `max_results` results of the search. 

        Note that each search results can have multiple definitions on different topics and each definition is a tuple of the term and its definition.
        So the number of results returned is `max_results` multiplied by the number of definitions per result, except a topic is specified in `under_topic`.
        """
        result_urls = self.get_terms_urls(topic, query=query, start_letter=start_letter, count=max_results)        
        return [ result for url in result_urls for result in self.get_term_details(topic or "", url) ]



