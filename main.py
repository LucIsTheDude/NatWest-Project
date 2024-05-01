# Python 3.10.11

# Importing necessary packages and libraries.
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from urllib.request import urlopen
import sqlite3
import os
import openai
from datetime import date

# Setting required variables.
apiKey = os.environ["OPENAI_API_KEY"]
openai.api_key = apiKey
model = "gpt-3.5-turbo"  # setting the model to use for the GPT API.

dateToday = date.today()  # Getting the current date.

# Connecting to the database (or creating it) and creating all 5 tables if they don't already exist.
connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.
connection.executescript('''
    CREATE TABLE IF NOT EXISTS BankDetails (
        BankID INTEGER PRIMARY KEY,
        BankName STRING UNIQUE,
        BankWebsite STRING
        );
    CREATE TABLE IF NOT EXISTS CurrencyType (
        CurrencyID INTEGER PRIMARY KEY,
        CurrencyName STRING UNIQUE,
        CurrencyCode STRING,
        CurrencySymbol CHAR(1),
        ExchangeRate REAL
        );
    CREATE TABLE IF NOT EXISTS BalanceRanges (
        BalanceRangeID INTEGER PRIMARY KEY,
        BalanceLowRange INTEGER,
        BalanceHighRange INTEGER,
        UNIQUE(BalanceLowRange, BalanceHighRange)
        );
    CREATE TABLE IF NOT EXISTS BankCurrency (
        BankCurrencyID INTEGER PRIMARY KEY,
        BankID INTEGER,
        CurrencyID INTEGER,
        FOREIGN KEY(BankID) REFERENCES BankDetails(BankID),
        FOREIGN KEY(CurrencyID) REFERENCES CurrencyType(CurrencyID),
        UNIQUE(BankID, CurrencyID)
        );
    CREATE TABLE IF NOT EXISTS InterestRates (
        DateEffective STRING,
        BankCurrencyID INTEGER,
        BalanceRangeID INTEGER,
        InterestRate REAL,
        FOREIGN KEY(BankCurrencyID) REFERENCES BankCurrency(BankCurrencyID),
        FOREIGN KEY(BalanceRangeID) REFERENCES BalanceRanges(BalanceRangeID),
        PRIMARY KEY(DateEffective, BankCurrencyID, BalanceRangeID),
        UNIQUE (BankCurrencyID, BalanceRangeID, InterestRate)
        );
    ''')
connection.close()


# Gathering a list of all bank names and currencies stored in the database.
def getBankNamesAndCurrencies(connection):
    bankNamesTuple = connection.execute("SELECT BankName FROM BankDetails").fetchall()  # Extracting the bank names.

    # Turning the tuple into a list.
    bankNames = []
    for bankNameTuple in bankNamesTuple:
        bankNames.append(bankNameTuple[0])

    currencyCodesTuple = connection.execute("SELECT CurrencyCode FROM CurrencyType").fetchall()  # Extracting the currency codes.

    # Turning the tuple into a list.
    currencyCodes = []
    for currencyCodeTuple in currencyCodesTuple:
        currencyCodes.append(currencyCodeTuple[0])

    return bankNames, currencyCodes


# Extracting the HTML code from the respective websites and placing each 'section' and 'table' into a list.
def findHTMLSections(url):
    html = urlopen(url).read().decode("utf-8")  # Extracting the HTML code from the website.
    soup = BeautifulSoup(html, "html.parser")  # Parsing the HTML code.
    sections = soup.find_all(["section", "table"])  # Extracting all the sections and tables from the HTML code.
    return sections


# Using the GPT API to determine if the sections of HTML code (in plaintext) include the interest rates we want.
def checkIfContainsInterestRates(sectionCheck, model):

    # Calling the GPT API to check if the section contains the interest rates we want.
    responseCheck = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "Your purpose is to inform if there are any AER interest rates with corresponding balance ranges contained within the text given to you. Only answer with 'yes' or 'no'."},
            {"role": "user", "content": sectionCheck}
        ],
        temperature=0,
    )
    output = responseCheck['choices'][0]['message']['content']  # Extracting the response from the API.
    return output


# Using the GPT API to extract the interest rates we want for the respective balance ranges in a format that allows for easy processing of the data.
def getArrayOfBalanceInterests(section, model):

    # Calling the GPT API to extract the interest rates for the respective balance ranges and formatting the output.
    response = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "Your purpose is to extract AER interest rates from the text provided for a given balance range. You remove any pound, comma or percentage characters. If one of the balance ranges is '£250,000+' for example, since there is a '+', you output '250000|0'. But if there was say '£10+' and '£100+', you output '10|99|AERInterestRate|100|0|AERInterestRate'. You output nothing but the results, and in the format: balanceLowerRange1|balanceUpperRange1|AERInterest1|balanceLowerRange2|balanceUpperRange2|AERInterest2|etcetera. Here is an example of an input: 'Balance    £1 - £29,999   £30,000 - £149,999   £150,000 - £199,999   £200,000+      AER p.a.    1.56%   2.86%   3.76%   4.20%      Gross p.a    1.50%   2.80%   3.70%   4.10%' and this is your output: '1|29999|1.56|30000|149999|2.86|150000|199999|3.76|200000|0|4.20'. Here is another example of an input: 'Balance    £1 - £24,999   £25,000 - £99,999   £100,000 - £249,999   £250,000+      AER p.a. (variable)    1.41%   2.12%   2.63%   3.14%      Gross p.a (variable)    1.40%   2.10%   2.60%   3.10%' and this is your output: '1|24999|1.41|25000|99999|2.12|100000|249999|2.63|250000|0|3.14'. Here is another example of an input: 'Current interest rates            Rates effective from      Balance      Gross per year %      AER %           1 September 2023        £1+       1.65        1.66              £10,000+        1.15        1.16' and this is your output: '1|9999|1.66|10000|0|1.16'"},
            {"role": "user", "content": section}
        ],
        temperature=0,
    )
    output = response['choices'][0]['message']['content']  # Extracting the response from the API.
    balanceInterests = output.split("|")  # Splitting the response into a list.
    return balanceInterests


# Inserting the balance ranges and interest rates into the database.
def insertIntoDatabase(balanceInterests, bankName):
    connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
    connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.

    # iterating through the balanceInterests list and inserting the data into the database.
    for i in range(0, len(balanceInterests) - 1, 3):

        # executing the SQL queries to insert the data into the database.
        connection.execute(
            "INSERT OR IGNORE INTO BalanceRanges (BalanceLowRange, BalanceHighRange) VALUES (?, ?)",
            (balanceInterests[i], balanceInterests[i + 1]))
        connection.execute(
            "INSERT OR IGNORE INTO BankCurrency (BankID, CurrencyID) VALUES ((SELECT BankID FROM BankDetails WHERE BankName = ?), (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = 'GBP'))",
            (bankName,))
        connection.execute(
            "INSERT OR IGNORE INTO InterestRates VALUES (?, ?, ?, ?)",
            (
                dateToday,
                connection.execute(
                    "SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?) AND CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = 'GBP')",
                    (bankName,)).fetchall()[0][0],
                connection.execute(
                    "SELECT BalanceRangeID FROM BalanceRanges WHERE BalanceLowRange = ? AND BalanceHighRange = ?",
                    (balanceInterests[i], balanceInterests[i + 1])).fetchall()[0][0],
                balanceInterests[i + 2]
            )
        )
    connection.commit()  # Committing the changes to the database.
    connection.close()


# The main function that links all the other functions together, it extracts all the data and automatically inserts it into the database.
def getInterestRatesAndInsertIntoDatabase(info, model, retries=3):
    try:
        sectionsOfHTML = findHTMLSections(info[1])  # Extracting the sections and tables of HTML code from the website as a list.
    except:
        # If there is no internet connection, the function will retry 3 times before returning "noInternet".
        if retries > 0:
            return getInterestRatesAndInsertIntoDatabase(info, model, retries - 1)
        else:
            return "noInternet"

    # Iterating through the sections and tables to find the one that contains the interest rates we want.
    for sectionCheck in sectionsOfHTML:
        sectionCheck = sectionCheck.get_text().strip().replace("\n", " ")  # Extracting the text from the section.
        yn = checkIfContainsInterestRates(sectionCheck, model)  # Checking if the section contains the interest rates we want (using the GPT API).

        # If the section contains the interest rates we want, the function will extract the data and insert it into the database.
        if "yes" in yn.lower():
            section = sectionCheck
            balanceInterests = getArrayOfBalanceInterests(section, model)  # Extracting the interest rates for the respective balance ranges (using the GPT API).
            insertIntoDatabase(balanceInterests, info[0])  # Inserting the data into the database.
            break  # Breaking the loop as the required data has already been extracted and inserted into the database.


# All the code below is for the Streamlit GUI.

# Creating all three tabs for the Streamlit GUI.
databaseTab, interestTab, graphingTab = st.tabs(["Database Manipulation", "Information and Predictions", "Graphing"])

# The first tab is for database manipulation.
with databaseTab:

    # Creating a central column for the title.
    _, mainCol, _ = st.columns([1, 7, 1])
    with mainCol:
        st.title("Instant Access Savings Data")

        # Creating two central columns for the buttons.
        _, midCol1, midCol2, _ = st.columns([1, 2, 2, 1])
        with midCol1:

            # The button that initiates the extraction and insertion of new data.
            if st.button("Gather Latest Data"):
                with st.spinner("Gathering Data..."):

                    # Inserting the required banks and currency types into the database (approximate exchange rates for currencies).
                    currencies = [
                        ["Pounds", "GBP", "£", 1],
                        ["Euros", "EUR", "€", 0.85],
                        ["US Dollars", "USD", "$", 0.8]
                    ]

                    banks = [
                        ["NatWest", "https://www.natwest.com/savings/flexible-saver.html"],
                        ["Barclays", "https://www.barclays.co.uk/savings/interest-rates/everyday-saver/"],
                        ["HSBC", "https://www.hsbc.co.uk/savings/products/flexible-saver/"],
                        ["Lloyd's Bank", "https://www.lloydsbank.com/savings/easy-saver.html"]
                    ]

                    connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
                    connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.
                    connection.executemany(
                        "INSERT OR IGNORE INTO CurrencyType (CurrencyName, CurrencyCode, CurrencySymbol, ExchangeRate) VALUES (?, ?, ?, ?)",
                        currencies)  # Inserting the currencies into the database.
                    connection.executemany("INSERT OR IGNORE INTO BankDetails (BankName, BankWebsite) VALUES (?, ?)", banks)  # Inserting the banks into the database.
                    connection.commit()  # Committing the changes to the database.
                    connection.close()

                    # Iterates through the dictionary of banks and calls the function that initiates the backend web scraping and data insertion for each bank.
                    for i in range(len(banks)):
                        info = banks[i]  # Extracting the bank name and website link.
                        result = getInterestRatesAndInsertIntoDatabase(info, model)

                # If there is no internet connection, the user will be notified.
                if result == "noInternet":
                    st.error("No internet connection detected. Please check your connection and try again.")
                else:
                    st.success("Done!")  # If the data extraction and insertion is successful, the user will be notified.

        with midCol2:

            # The download button to allow the user to download the database.
            with open("database.sqlite", "rb") as fp:
                st.download_button(
                    label="Download Database",
                    data=fp,
                    file_name="database.sqlite",
                    mime="application/octet-stream"
                )

    st.divider()  # Creating a divider to separate the title and the rest of the content.
    st.subheader("Database Manipulation:")  # Creating a subheader for the database manipulation section.

    st.write("")  # Creating a space between the subheader and the content.
    st.write("Database Read Operations:")  # Writing a title for the read operations section.

    # Allows the user to display the data for any one of the tables in the database.
    with st.expander("Display a Table"):
        connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
        connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.

        # Extracting the table names from the database.
        tableNamesTuple = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ").fetchall()
        tableNames = []

        # Turning the tuple into a list.
        for tableNameTuple in tableNamesTuple:
            tableNames.append(tableNameTuple[0])

        # Creating a dropdown menu for the user to select which table they want to display.
        option = st.selectbox("Select which table you want:", tableNames, index=None, placeholder="Select a table...")

        # If the user selects a table, the data from that table will be displayed.
        if option:
            query = "SELECT * FROM " + option
            df = pd.read_sql_query(query, connection)  # Extracting the data from the table as a dataframe.
            st.dataframe(df)  # Displaying the table as a dataframe.
            st.caption("(0 means infinite)")
        connection.close()

    # Allows the user to display specific data from the database, including referencing other tables.
    with st.expander("Display Specific Data from the Database"):

        # Creating a dropdown menu for the user to select one of the three options below.
        choices = ["View Interest Rates", "View the Currencies for Each Bank", "View the Website for Each Bank"]
        choice = st.selectbox("Select an option:", choices, index=None, placeholder="Select an option...")

        # If the user selects an option, they will be able to select the banks they want to see the data for.
        if choice:
            connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
            connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.

            # Extracting the bank names from the database.
            bankNamesTuple = connection.execute("SELECT BankName FROM BankDetails").fetchall()

            # Turning the tuple into a list.
            bankNames = []
            for bankNameTuple in bankNamesTuple:
                bankNames.append(bankNameTuple[0])

            # Creating a multiselect dropdown menu for the user to select the banks they want to see the data for.
            user_bankNames = st.multiselect("Select the banks you would like to see the data for:", bankNames,
                                            placeholder="Select banks...")

            # If the user selects banks, the data for the selected banks will be displayed.
            if user_bankNames:
                questionMarks = ", ".join("?" * len(user_bankNames))  # Creating a string of question marks for the SQL query.

                # If the user selects to 'View Interest Rates', the interest rates for the selected banks will be displayed.
                if choice == choices[0]:
                    query = f"SELECT BankName, BalanceLowRange, BalanceHighRange, InterestRate, CurrencyCode, DateEffective FROM BankDetails JOIN BankCurrency USING (BankID) JOIN InterestRates USING (BankCurrencyID) JOIN BalanceRanges USING (BalanceRangeID) JOIN CurrencyType USING (CurrencyID) WHERE BankName IN ({questionMarks})"

                    # If the user selects to only see today's interest rates, the query will be updated accordingly.
                    if st.checkbox("Show Only Today's Interest Rates"):
                        query += " AND DateEffective = ?"
                        user_bankNames.append(dateToday)

                    # If the user selects to sort the table by the interest rates, the query will be updated accordingly.
                    if st.checkbox("Sort By Interest Rate"):
                        query += " ORDER BY InterestRate DESC"

                    df = pd.read_sql_query(query, connection, params=user_bankNames)  # Extracting the data from the database.
                    st.dataframe(df)  # Displaying the data as a dataframe.
                    st.caption("(0 means infinite)")

                # If the user selects to 'View the Currencies for Each Bank', the currencies for the selected banks will be displayed.
                elif choice == choices[1]:
                    query = f"SELECT BankName, CurrencyName, CurrencyCode, CurrencySymbol FROM BankDetails JOIN BankCurrency USING (BankID) JOIN CurrencyType USING (CurrencyID) WHERE BankName IN ({questionMarks})"

                    df = pd.read_sql_query(query, connection, params=user_bankNames)  # Extracting the data from the database.
                    st.dataframe(df)  # Displaying the data as a dataframe.

                # If the user selects to 'View the Website for Each Bank', the websites for the selected banks will be displayed.
                elif choice == choices[2]:
                    query = f"SELECT BankName, BankWebsite FROM BankDetails WHERE BankName IN ({questionMarks})"

                    df = pd.read_sql_query(query, connection, params=user_bankNames)  # Extracting the data from the database.
                    st.dataframe(df)  # Displaying the data as a dataframe.

            connection.close()

    st.write("")  # Creating a space between the read and write operations.
    st.write("Database Write Operations:")  # Writing a title for the write operations section.

    # Allows the user to add data to the database.
    with st.expander("Add Data to the Database"):
        connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
        connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.

        # Creating a dropdown menu for the user to select one of the three options below.
        choices = ["Add a Bank", "Add an Interest Rate", "Add a Currency"]
        choice = st.selectbox("Select an option:", choices, index=None, placeholder="Select an option...")
        st.write(
            "NOTE: This is for manual data entry, data entered here wont be automatically updated or extracted when the 'Gather Latest Data' button is pressed.")

        # If the user selects to 'Add a Bank', they will be able to add a new bank to the database.
        if choice == choices[0]:
            bankName = st.text_input("Enter the name of the bank:")  # Text input for the bank name.
            bankWebsite = st.text_input("Enter the website link to the instant access savings page of the bank:")  # Text input for the bank website.

            # If the user presses the button, the data will be inserted into the database.
            if st.button("Add Bank"):
                try:
                    connection.execute("INSERT INTO BankDetails (BankName, BankWebsite) VALUES (?, ?)",
                                       (bankName, bankWebsite))
                    connection.commit()
                    st.write("Bank added successfully!")  # If the data is inserted successfully, the user will be notified.
                except:
                    st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

        # If the user selects to 'Add an Interest Rate', they will be able to add a new interest rate to the database.
        elif choice == choices[1]:
            bankNames, currencyCodes = getBankNamesAndCurrencies(connection)  # Extracting the bank names and currency codes from the database.

            bankName = st.selectbox("Select the bank you want to add an interest rate for:", bankNames, index=None,
                                    placeholder="Select a bank..")  # Dropdown menu for the bank names.
            currencyCode = st.selectbox("Select the currency for this interest rate:", currencyCodes, index=None,
                                        placeholder="Select a currency...")  # Dropdown menu for the currency codes.
            balanceLowRange = st.text_input("Enter the lower boundary of the balance range (INTEGER VALUES ONLY):",
                                            value=None, placeholder="Enter a number...")  # Text input for the lower boundary of the balance range.
            balanceHighRange = st.text_input("Enter the upper boundary of the balance range (INTEGER VALUES ONLY):",
                                             value=None, placeholder="Enter a number...")  # Text input for the upper boundary of the balance range.
            interestRate = st.text_input("Enter the interest rate for the balance range:", value=None,
                                         placeholder="Enter a number...")  # Text input for the interest rate.

            # If the user presses the button, the data will be inserted into the database.
            if st.button("Add Interest Rate"):
                try:
                    balanceLowRange = int(balanceLowRange)
                    balanceHighRange = int(balanceHighRange)
                    interestRate = float(interestRate)
                    connection.execute(
                        "INSERT OR IGNORE INTO BalanceRanges (BalanceLowRange, BalanceHighRange) VALUES (?, ?)",
                        (balanceLowRange, balanceHighRange))
                    connection.execute(
                        "INSERT OR IGNORE INTO BankCurrency (BankID, CurrencyID) VALUES ((SELECT BankID FROM BankDetails WHERE BankName = ?), (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?))",
                        (bankName, currencyCode))
                    connection.execute(
                        "INSERT OR IGNORE INTO InterestRates VALUES (?, (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?) AND CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?)), (SELECT BalanceRangeID FROM BalanceRanges WHERE BalanceLowRange = ? AND BalanceHighRange = ?), ?)",
                        (dateToday, bankName, currencyCode, balanceLowRange, balanceHighRange, interestRate))
                    connection.commit()
                    st.write("Interest rate added successfully!")  # If the data is inserted successfully, the user will be notified.
                except:
                    st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

        # If the user selects to 'Add a Currency', they will be able to add a new currency to the database.
        elif choice == choices[2]:
            currencyName = st.text_input("Enter the name of the currency:")  # Text input for the currency name.
            currencyCode = st.text_input("Enter the currency code:")  # Text input for the currency code.
            currencySymbol = st.text_input("Enter the currency symbol (SINGLE CHARACTER):")  # Text input for the currency symbol.
            exchangeRate = st.text_input("Enter the exchange rate to GBP (multiplier for this currency to give GBP):")  # Text input for the exchange rate to Pounds.

            # If the user presses the button, the data will be inserted into the database.
            if st.button("Add Currency"):
                try:
                    exchangeRate = float(exchangeRate)
                    connection.execute(
                        "INSERT OR IGNORE INTO CurrencyType (CurrencyName, CurrencyCode, CurrencySymbol, ExchangeRate) VALUES (?, ?, ?, ?)",
                        (currencyName, currencyCode, currencySymbol, exchangeRate))
                    connection.commit()
                    st.write("Currency added successfully!")  # If the data is inserted successfully, the user will be notified.
                except:
                    st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

        connection.close()

    # Allows the user to delete data from the database.
    with st.expander("Delete Data from the Database"):
        connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
        connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.

        # Creating a dropdown menu for the user to select one of the three options below.
        choices = ["Delete a Bank", "Delete an Interest Rate", "Delete a Currency"]
        choice = st.selectbox("Select an option:", choices, index=None, placeholder="Select an option...")

        # If the user selects to 'Delete a Bank', they will be able to delete a bank from the database.
        if choice == choices[0]:
            st.write("WARNING: Deleting a bank will delete all it's associated interest rates as well.")  # Warning message.

            # Extracting the bank names from the database.
            bankNamesTuple = connection.execute("SELECT BankName FROM BankDetails").fetchall()

            # Turning the tuple into a list.
            bankNames = []
            for bankNameTuple in bankNamesTuple:
                bankNames.append(bankNameTuple[0])

            bankName = st.selectbox("Select the bank you want to delete:", bankNames, index=None, placeholder="Select a bank..")  # Dropdown menu for the bank names.

            # If the user presses the button, the data will be deleted from the database.
            if st.button("Delete Bank"):
                connection.execute("DELETE FROM InterestRates WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?))", (bankName,))
                connection.execute("DELETE FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?)", (bankName,))
                connection.execute("DELETE FROM BankDetails WHERE BankName = ?", (bankName,))
                connection.execute("DELETE FROM BalanceRanges WHERE BalanceRangeID NOT IN (SELECT BalanceRangeID FROM InterestRates)")
                connection.commit()
                st.write("Bank deleted successfully!")  # If the data is deleted successfully, the user will be notified.

        # If the user selects to 'Delete an Interest Rate', they will be able to delete an interest rate from the database.
        elif choice == choices[1]:
            bankNames, currencyCodes = getBankNamesAndCurrencies(connection)  # Extracting the bank names and currency codes from the database.

            bankName = st.selectbox("Select the bank you want to delete an interest rate from:", bankNames, index=None, placeholder="Select a bank..")  # Dropdown menu for the bank names.
            currencyCode = st.selectbox("Select the currency for this interest rate:", currencyCodes, index=None, placeholder="Select a currency...")  # Dropdown menu for the currency codes.
            interestRatesTuple = connection.execute("SELECT InterestRate FROM InterestRates WHERE BankCurrencyID IN (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?) AND CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?))", (bankName, currencyCode)).fetchall()  # Extracting the interest rates for the selected bank and currency.

            # Turning the tuple into a list.
            interestRates = []
            for interestRateTuple in interestRatesTuple:
                interestRates.append(interestRateTuple[0])

            if not interestRates:
                st.write("No interest rates found for this bank and currency.")  # If there are no interest rates, the user will be notified.
            else:
                interestRate = st.selectbox("Select the interest rate you want to delete:", interestRates, index=None, placeholder="Select an interest rate...")  # Dropdown menu for the interest rates.

            # If the user presses the button, the data will be deleted from the database.
            if st.button("Delete Interest Rate"):
                connection.execute("DELETE FROM InterestRates WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?) AND CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?)) AND InterestRate = ?", (bankName, currencyCode, interestRate))
                connection.execute("DELETE FROM BalanceRanges WHERE BalanceRangeID NOT IN (SELECT BalanceRangeID FROM InterestRates)")
                connection.commit()
                st.write("Interest rate deleted successfully!")  # If the data is deleted successfully, the user will be notified.

        # If the user selects to 'Delete a Currency', they will be able to delete a currency from the database.
        elif choice == choices[2]:
            st.write("WARNING: Deleting a currency will delete all the associated interest rates as well.")  # Warning message.

            # Extracting the currency codes from the database.
            currencyCodesTuple = connection.execute("SELECT CurrencyCode FROM CurrencyType").fetchall()

            # Turning the tuple into a list.
            currencyCodes = []
            for currencyCodeTuple in currencyCodesTuple:
                currencyCodes.append(currencyCodeTuple[0])

            currencyCode = st.selectbox("Select the currency you want to delete:", currencyCodes, index=None, placeholder="Select a currency...")  # Dropdown menu for the currency codes.

            # If the user presses the button, the data will be deleted from the database.
            if st.button("Delete Currency"):
                connection.execute("DELETE FROM InterestRates WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?))", (currencyCode,))
                connection.execute("DELETE FROM BankCurrency WHERE CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?)", (currencyCode,))
                connection.execute("DELETE FROM CurrencyType WHERE CurrencyCode = ?", (currencyCode,))
                connection.execute("DELETE FROM BalanceRanges WHERE BalanceRangeID NOT IN (SELECT BalanceRangeID FROM InterestRates)")
                connection.commit()
                st.write("Currency deleted successfully!")  # If the data is deleted successfully, the user will be notified.

        connection.close()

    # Allows the user to amend data in the database.
    with st.expander("Amend Data in the Database"):
        connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
        connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.

        # Creating a dropdown menu for the user to select one of the three options below.
        choices = ["Amend a Bank", "Amend an Interest Rate", "Amend a Currency"]
        choice = st.selectbox("Select an option:", choices, index=None, placeholder="Select an option...")

        # If the user selects to 'Amend a Bank', they will be able to amend a bank in the database.
        if choice == choices[0]:

            # Extracting the bank names from the database.
            bankNamesTuple = connection.execute("SELECT BankName FROM BankDetails").fetchall()

            # Turning the tuple into a list.
            bankNames = []
            for bankNameTuple in bankNamesTuple:
                bankNames.append(bankNameTuple[0])

            bankName = st.selectbox("Select the bank you want to amend:", bankNames, index=None, placeholder="Select a bank..")  # Dropdown menu for the bank names.

            # Creating a dropdown menu for the user to select one of the two options below.
            bankChoices = ["Amend Bank Name", "Amend Bank Website"]
            bankChoice = st.selectbox("Select what you want to amend:", bankChoices, index=None, placeholder="Select an option...")

            # If the user selects to 'Amend Bank Name', they will be able to amend the name of the bank.
            if bankChoice == bankChoices[0]:
                newBankName = st.text_input("Enter the new name for the bank:", value=None, placeholder="Enter a name...")  # Text input for the new bank name.
                if st.button("Amend Bank"):
                    try:
                        connection.execute("UPDATE BankDetails SET BankName = ? WHERE BankName = ?", (newBankName, bankName))
                        connection.commit()
                        st.write("Bank amended successfully!")  # If the data is amended successfully, the user will be notified.
                    except:
                        st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

            # If the user selects to 'Amend Bank Website', they will be able to amend the website of the bank.
            elif bankChoice == bankChoices[1]:
                newBankWebsite = st.text_input("Enter the new website link to the instant access savings page of the bank:", value=None, placeholder="Enter a link...")  # Text input for the new bank website.
                if st.button("Amend Bank"):
                    try:
                        connection.execute("UPDATE BankDetails SET BankWebsite = ? WHERE BankName = ?", (newBankWebsite, bankName))
                        connection.commit()
                        st.write("Bank amended successfully!")  # If the data is amended successfully, the user will be notified.
                    except:
                        st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

        # If the user selects to 'Amend an Interest Rate', they will be able to amend an interest rate in the database.
        elif choice == choices[1]:
            bankNames, currencyCodes = getBankNamesAndCurrencies(connection)  # Extracting the bank names and currency codes from the database.

            bankName = st.selectbox("Select the bank you want to amend an interest rate for:", bankNames, index=None, placeholder="Select a bank..")  # Dropdown menu for the bank names.
            currencyCode = st.selectbox("Select the currency for this interest rate:", currencyCodes, index=None, placeholder="Select a currency...")  # Dropdown menu for the currency codes.
            interestRatesTuple = connection.execute("SELECT InterestRate FROM InterestRates WHERE BankCurrencyID IN (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?) AND CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?))", (bankName, currencyCode)).fetchall()  # Extracting the interest rates for the selected bank and currency.

            # Turning the tuple into a list.
            interestRates = []
            for interestRateTuple in interestRatesTuple:
                interestRates.append(interestRateTuple[0])

            interestRate = st.selectbox("Select the interest rate you want to amend:", interestRates, index=None, placeholder="Select an interest rate...")  # Dropdown menu for the interest rates.

            # if the user selects an interest rate, they will be able to amend the interest rate for the balance range.
            if bankName and currencyCode and interestRate:
                balanceRangesTuple = connection.execute("SELECT BalanceLowRange, BalanceHighRange FROM BalanceRanges WHERE BalanceRangeID = (SELECT BalanceRangeID FROM InterestRates WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?) AND CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?)) AND InterestRate = ?)", (bankName, currencyCode, interestRate)).fetchall()  # Extracting the balance ranges for the selected bank, currency, and interest rate.

                balanceLowRange = str(balanceRangesTuple[0][0])  # Extracting the lower boundary of the balance range.
                balanceHighRange = str(balanceRangesTuple[0][1])  # Extracting the upper boundary of the balance range.

                st.write("This interest rate is for the balance range: £" + balanceLowRange + " - £" + balanceHighRange)  # Displaying the balance range.
                st.caption("(0 means infinite)")
                newInterestRate = st.text_input("Enter the new interest rate for the balance range:", value=None, placeholder="Enter a number...")  # Dropdown menu for the interest rates.

                #
                if st.button("Amend Interest Rate"):
                    try:
                        newInterestRate = float(newInterestRate)
                        connection.execute("UPDATE InterestRates SET InterestRate = ? WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?) AND CurrencyID = (SELECT CurrencyID FROM CurrencyType WHERE CurrencyCode = ?)) AND InterestRate = ?", (newInterestRate, bankName, currencyCode, interestRate))
                        connection.commit()
                        st.write("Interest rate amended successfully!")  # If the data is amended successfully, the user will be notified.
                    except:
                        st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

        # If the user selects to 'Amend a Currency', they will be able to amend a currency in the database.
        elif choice == choices[2]:

            # Extracting the currency codes from the database.
            currencyCodesTuple = connection.execute("SELECT CurrencyCode FROM CurrencyType").fetchall()

            # Turning the tuple into a list.
            currencyCodes = []
            for currencyCodeTuple in currencyCodesTuple:
                currencyCodes.append(currencyCodeTuple[0])

            currencyCode = st.selectbox("Select the currency you want to amend:", currencyCodes, index=None, placeholder="Select a currency...")  # Dropdown menu for the currency codes.

            # Creating a dropdown menu for the user to select one of the three options below.
            currencyChoices = ["Amend Currency Name", "Amend Currency Symbol", "Amend Exchange Rate"]
            currencyChoice = st.selectbox("Select what you want to amend:", currencyChoices, index=None, placeholder="Select an option...")  # Dropdown menu for the currency choices.

            # If the user selects to 'Amend Currency Name', they will be able to amend the name of the currency.
            if currencyChoice == currencyChoices[0]:
                newCurrencyName = st.text_input("Enter the new name for the currency:", value=None, placeholder="Enter a name...")  # Text input for the new currency name.
                if st.button("Amend Currency"):
                    try:
                        connection.execute("UPDATE CurrencyType SET CurrencyName = ? WHERE CurrencyCode = ?", (newCurrencyName, currencyCode))
                        connection.commit()
                        st.write("Currency amended successfully!")  # If the data is amended successfully, the user will be notified.
                    except:
                        st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

            # If the user selects to 'Amend Currency Symbol', they will be able to amend the symbol of the currency.
            elif currencyChoice == currencyChoices[1]:
                newCurrencySymbol = st.text_input("Enter the new symbol for the currency (SINGLE CHARACTER):", value=None, placeholder="Enter a character...")  # Text input for the new currency symbol.
                if st.button("Amend Currency"):
                    try:
                        connection.execute("UPDATE CurrencyType SET CurrencySymbol = ? WHERE CurrencyCode = ?", (newCurrencySymbol, currencyCode))
                        connection.commit()
                        st.write("Currency amended successfully!")  # If the data is amended successfully, the user will be notified.
                    except:
                        st.write("Invalid Inputs")  # If the user enters invalid inputs, they will be notified.

            # If the user selects to 'Amend Exchange Rate', they will be able to amend the exchange rate of the currency.
            elif currencyChoice == currencyChoices[2]:
                newExchangeRate = st.text_input("Enter the new exchange rate to GBP (multiplier for this currency to give GBP):", value=None, placeholder="Enter a number...")  # Text input for the new exchange rate.
                if st.button("Amend Currency"):
                    try:
                        newExchangeRate = float(newExchangeRate)
                        connection.execute("UPDATE CurrencyType SET ExchangeRate = ? WHERE CurrencyCode = ?", (newExchangeRate, currencyCode))
                        connection.commit()
                        st.write("Currency amended successfully!")
                    except:
                        st.write("Invalid Inputs")
        connection.close()

    # Button to reset the database.
    if st.button("Reset Database"):
        connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
        connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.
        connection.executescript('''
            DELETE FROM InterestRates;
            DELETE FROM BankCurrency;
            DELETE FROM BalanceRanges;
            DELETE FROM CurrencyType;
            DELETE FROM BankDetails;
            ''')
        connection.commit()  # Committing the changes to the database.
        connection.close()
        st.write("Database reset successfully!")


# The second tab is for seeing what interest rate you could have on your savings balance and optionally give predictions.
with interestTab:

    # Creating a central column for the title.
    _, mainCol, _ = st.columns([1, 6, 1])
    with mainCol:
        st.title("What is the interest rate for your savings balance?")

    st.divider()  # Creating a divider to separate the title and the content.

    num = st.text_input("Enter your current savings balance:", value=None, placeholder="Enter a number...")  # Text input for the user's savings balance.

    # If the user enters a savings amount, the code will run.
    if num:

        # Input validation
        valid = False
        try:
            num = round(float(num), 2)
            valid = True
        except:
            st.write("Invalid Input")  # If the user enters an invalid input, they will be notified.

        # If the user enters a valid input, the code will run.
        if valid:
            connection = sqlite3.connect("database.sqlite")  # Connecting to the database.
            connection.execute("PRAGMA foreign_keys = ON")  # Enabling foreign key constraints.

            # Extracting the bank names from the database.
            bankNamesTuple = connection.execute("SELECT BankName FROM BankDetails").fetchall()

            # Turning the tuple into a list.
            bankNames = []
            for bankNameTuple in bankNamesTuple:
                bankNames.append(bankNameTuple[0])

            st.text("")  # Creating a space between the text input and the dropdown menu.
            option = st.selectbox("Select the bank you're considering:", bankNames)  # Dropdown menu for the bank names.

            # If the user selects a bank, the code will run.
            if option:
                balanceRangesTuple = connection.execute(
                    "SELECT BalanceLowRange, BalanceHighRange FROM BalanceRanges WHERE BalanceRangeID IN (SELECT BalanceRangeID FROM InterestRates WHERE BankCurrencyID IN (SELECT BankCurrencyID FROM BankCurrency WHERE BankID IN (SELECT BankID FROM BankDetails WHERE BankName = ?)))",
                    (option,)).fetchall()  # Extracting the balance ranges for the selected bank.

                # Turning the tuple into a list.
                balanceRanges = []
                for balancesTuple in balanceRangesTuple:
                    for i in balancesTuple:
                        balanceRanges.append(i)

                balanceRanges_updated = balanceRanges.copy()  # Creating a copy of the balance ranges list.

                # Replacing 0 with infinity in the balanceRanges_updated list.
                for i in range(1, len(balanceRanges_updated), 2):
                    if balanceRanges_updated[i] == 0:
                        balanceRanges_updated[i] = float("inf")

                interestRate = None  # Default value if no interest rate is found.

                # Iterating through the balance ranges to find the interest rate for the user's savings balance.
                for i in range(0, len(balanceRanges_updated), 2):
                    if balanceRanges_updated[i] <= num < (balanceRanges_updated[i + 1] + 1):
                        interestRate = connection.execute(
                            "SELECT InterestRate FROM InterestRates WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?)) AND BalanceRangeID = (SELECT BalanceRangeID FROM BalanceRanges WHERE BalanceLowRange = ? AND BalanceHighRange = ?)",
                            (option, balanceRanges[i], balanceRanges[i + 1])).fetchall()[0][0]  # Extracting the interest rate for the user's savings balance, using the original balanceRanges list.
                        break  # Exiting the loop if the interest rate is found.

                st.write("")  # Creating a space between the dropdown menu and the content.

                # If the interest rate is not found, the user will be notified.
                if interestRate is None:
                    st.write("##### This bank has not supplied an interest rate for your savings amount.")  # If the interest rate is not found, the user will be notified.
                else:

                    # Creating a central column for the content.
                    _, interestCol, _ = st.columns([1, 3, 1])
                    with interestCol:
                        st.write("#### Your savings interest rate is: " + str(interestRate) + "% AER\n###### This is for a balance between £" + str(balanceRanges[i]) + " and £" + str(balanceRanges[i + 1]) + ".")  # Displaying the interest rate for the user's savings balance.
                        st.caption("(0 means infinite)")

                        st.write("")  # Creating a space between the interest rate and the predictions.

                        predictions = st.checkbox("Would you like to see how your savings balance could grow over time?")  # Checkbox for the user to choose if they want to see predictions.

                        st.write("")  # Creating a space between the predictions and the text input.

                        # If the user selects to see predictions, the code will run.
                        if predictions:
                            years = st.text_input("Enter the number of years you plan to save for:", value=None, placeholder="Enter a number...")  # Text input for the number of years the user plans to save for.
                            st.write("This should be a whole number of years.")

                            st.write("")  # Creating a space between the text input and the predictions.

                            # If the user enters the number of years, the code will run.
                            if years:

                                # Input validation
                                valid = False
                                try:
                                    years = int(years)
                                    valid = True
                                except:
                                    st.write("Invalid Input")  # If the user enters an invalid input, they will be notified.

                                # If the user enters a valid input, the code will run.
                                if valid:
                                    balance = num  # Setting the user's savings balance as the initial balance.

                                    # Iterating through the years to predict the user's savings balance.
                                    for i in range(years):
                                        for j in range(0, len(balanceRanges_updated), 2):

                                            # Check if balance has moved to a new range at the end of each year.
                                            if balanceRanges_updated[j] <= balance < (balanceRanges_updated[j + 1] + 1):
                                                interestRate = connection.execute(
                                                    "SELECT InterestRate FROM InterestRates WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?)) AND BalanceRangeID = (SELECT BalanceRangeID FROM BalanceRanges WHERE BalanceLowRange = ? AND BalanceHighRange = ?)",
                                                    (option, balanceRanges[j], balanceRanges[j + 1])).fetchall()[0][0]  # Extracting the new interest rate for the user's increased savings balance, using the original balanceRanges list.
                                                break  # Exiting the loop if the interest rate is found.

                                        balance += balance * (interestRate / 100)  # Calculating the new savings balance after the interest is added.

                                    st.write("###### Your savings balance after " + str(years) + " years is predicted to be:\n#### £" + str(round(balance, 2)))  # Displaying the predicted savings balance after the specified number of years.

            connection.close()


# The fourth tab is for graphing the data.
with graphingTab:

    # Creating a central column for the title.
    _, titleCol, _ = st.columns([1, 7, 1])
    with titleCol:
        st.title("Graphing Interest Rate against Savings Balance")

    st.divider()  # Creating a divider to separate the title and the content.

    st.write("This function is currently under development.")
