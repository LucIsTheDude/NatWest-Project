# Importing necessary packages and libraries.
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from urllib.request import urlopen
import sqlite3
import os
import openai
from datetime import date

# Setting required variables
apiKey = os.environ["OPENAI_API_KEY"]
openai.api_key = apiKey
model = "gpt-3.5-turbo"

dateToday = date.today()

# Connecting to the database and creating a table if one doesn't already exist.
connection = sqlite3.connect("database.sqlite")
connection.execute("PRAGMA foreign_keys = ON")
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
        PRIMARY KEY(DateEffective, BankCurrencyID, BalanceRangeID)
        );
    ''')
connection.close()


# Extracting the HTML code from the respective websites and placing each section into an array.
def findHTMLSections(url):
    html = urlopen(url).read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.find_all(["section", "table"])
    return sections


# Using the GPT API to determine if the sections of HTML code (in plaintext) include the interest rates we want.
def checkIfContainsInterestRates(sectionCheck, model):
    responseCheck = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "Your purpose is to inform if there are any AER interest rates with corresponding balance ranges contained within the text given to you. Only answer with 'yes' or 'no'."},
            {"role": "user", "content": sectionCheck}
        ],
        temperature=0,
    )
    output = responseCheck['choices'][0]['message']['content']
    return output


# Using the GPT API to extract the interest rates we want for the respective balance ranges in a format that allows for easy processing of the data.
def getArrayOfBalanceInterests(section, model):
    response = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "Your purpose is to extract AER interest rates from the text provided for a given balance range. You remove any pound, comma or percentage characters. If one of the balance ranges is '£250,000+' for example, since there is a '+', you output '250000|0'. But if there was say '£10+' and '£100+', you output '10|99|AERInterestRate|100|0|AERInterestRate'. You output nothing but the results, and in the format: balanceLowerRange1|balanceUpperRange1|AERInterest1|balanceLowerRange2|balanceUpperRange2|AERInterest2|etcetera. Here is an example of an input: 'Balance    £1 - £29,999   £30,000 - £149,999   £150,000 - £199,999   £200,000+      AER p.a.    1.56%   2.86%   3.76%   4.20%      Gross p.a    1.50%   2.80%   3.70%   4.10%' and this is your output: '1|29999|1.56|30000|149999|2.86|150000|199999|3.76|200000|0|4.20'. Here is another example of an input: 'Balance    £1 - £24,999   £25,000 - £99,999   £100,000 - £249,999   £250,000+      AER p.a. (variable)    1.41%   2.12%   2.63%   3.14%      Gross p.a (variable)    1.40%   2.10%   2.60%   3.10%' and this is your output: '1|24999|1.41|25000|99999|2.12|100000|249999|2.63|250000|0|3.14'. Here is another example of an input: 'Current interest rates            Rates effective from      Balance      Gross per year %      AER %           1 September 2023        £1+       1.65        1.66              £10,000+        1.15        1.16' and this is your output: '1|9999|1.66|10000|0|1.16'"},
            {"role": "user", "content": section}
        ],
        temperature=0,
    )
    output = response['choices'][0]['message']['content']
    balanceInterests = output.split("|")
    return balanceInterests


# Inserting the data into the database.
def insertIntoDatabase(balanceInterests, bankName):
    connection = sqlite3.connect("database.sqlite")
    connection.execute("PRAGMA foreign_keys = ON")
    for i in range(0, len(balanceInterests) - 1, 3):
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
    connection.commit()
    connection.close()


# The main function that links all the other functions together, it extracts all the data and automatically inserts it into the database.
def getInterestRatesAndInsertIntoDatabase(info, model):
    sectionsOfHTML = findHTMLSections(info[1])
    for sectionCheck in sectionsOfHTML:
        sectionCheck = sectionCheck.get_text().strip().replace("\n", " ")
        yn = checkIfContainsInterestRates(sectionCheck, model)
        if "yes" in yn.lower():
            section = sectionCheck
            balanceInterests = getArrayOfBalanceInterests(section, model)
            insertIntoDatabase(balanceInterests, info[0])
            break


# All the code below is for the Streamlit GUI.
databaseTab, interestTab = st.tabs(["Database Manipulation", "Interest Rates"])

# The first tab is for database manipulation.
with databaseTab:
    _, mainCol, _ = st.columns([1, 7, 1])

    with mainCol:
        st.title("Instant Access Savings Data")

        _, midCol1, midCol2, _ = st.columns([1, 2, 2, 1])

        with midCol1:
            # The button that initiates the extraction and insertion of new data.
            if st.button("Gather Latest Data"):

                # Inserting the required banks and currency types into the database (approximate exchange rates for currencies).
                currencies = [
                    ["Pounds", "GBP", "£", 1],
                    ["Euros", "EUR", "€", 0.85],
                    ["US Dollars", "USD", "$", 0.8]
                ]

                banks = [
                    ["NatWest", "https://www.natwest.com/savings/flexible-saver.html"],
                    ["Barclays", "https://www.barclays.co.uk/savings/interest-rates/everyday-saver/"],
                    ["HSBC", "https://www.hsbc.co.uk/savings/products/flexible-saver/"]
                ]

                connection = sqlite3.connect("database.sqlite")
                connection.execute("PRAGMA foreign_keys = ON")
                connection.executemany(
                    "INSERT OR IGNORE INTO CurrencyType (CurrencyName, CurrencyCode, CurrencySymbol, ExchangeRate) VALUES (?, ?, ?, ?)",
                    currencies)
                connection.executemany("INSERT OR IGNORE INTO BankDetails (BankName, BankWebsite) VALUES (?, ?)", banks)
                connection.commit()
                connection.close()

                # calls the function that initiates the backend web scraping and data insertion for each bank.
                for i in range(len(banks)):
                    info = banks[i]
                    getInterestRatesAndInsertIntoDatabase(info, model)

                st.write("Done")

        with midCol2:
            # The download button to allow the user to download the database easily.
            with open("database.sqlite", "rb") as fp:
                st.download_button(
                    label="Download Database",
                    data=fp,
                    file_name="database.sqlite",
                    mime="application/octet-stream"
                )

    st.divider()
    st.subheader("Database Manipulation:")

    # Displaying the data for any one of the tables in the database.
    with st.expander("Display a table"):
        connection = sqlite3.connect("database.sqlite")
        connection.execute("PRAGMA foreign_keys = ON")
        tableNamesTuple = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ").fetchall()
        tableNames = []
        for balancesTuple in tableNamesTuple:
            tableNames.append(balancesTuple[0])
        option = st.selectbox(
            "Select which table you want:", tableNames)
        if option:
            query = "SELECT * FROM " + option
            df = pd.read_sql_query(query, connection)
            st.dataframe(df)
            st.caption("(0 means infinite)")
        connection.close()

    # Executing SQL Read Queries to display specific data from the table.
    readQuery = st.text_input("Enter a READ SQL query here:")

    if readQuery:
        connection = sqlite3.connect("database.sqlite")
        connection.execute("PRAGMA foreign_keys = ON")
        if st.button("Run/Refresh Read Query"):
            try:
                df = pd.read_sql_query(readQuery, connection)
                st.dataframe(df)
                st.caption("(0 means infinite)")
            except:
                st.write("Invalid Query")
        connection.close()

    st.text("")

    # Executing SQL Write Queries to add, edit or delete data from the table.
    writeQuery = st.text_input("Enter a WRITE SQL query here:")

    if writeQuery:
        connection = sqlite3.connect("database.sqlite")
        connection.execute("PRAGMA foreign_keys = ON")
        if writeQuery[0:6].lower() == "create":
            st.write("This is only for dealing with the current tables.")
        else:
            try:
                connection.execute(writeQuery)
            except:
                st.write("Invalid Query")
            # df = pd.read_sql_query("SELECT * FROM data", connection)
            # st.dataframe(df)
            # st.caption("(0 means infinite)")
            if st.button("Commit Changes to Database"):
                connection.commit()
                st.write("Changes committed successfully!")
        connection.close()

    if st.button("Reset Database"):
        connection = sqlite3.connect("database.sqlite")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript('''
            DELETE FROM InterestRates;
            DELETE FROM BankCurrency;
            DELETE FROM BalanceRanges;
            DELETE FROM CurrencyType;
            DELETE FROM BankDetails;
            ''')
        connection.commit()
        connection.close()
        st.write("Database reset successfully!")

# The second tab is for savings predictions.
with interestTab:
    _, mainCol, _ = st.columns([1, 6, 1])

    with mainCol:
        st.title("What is the interest rate for your savings balance?")

    st.divider()

    num = st.text_input("Enter your current savings balance:", value=None, placeholder="Enter a number...")

    if num:
        valid = False
        try:
            num = float(num)
            valid = True
        except:
            st.write("Invalid Input")

        if valid:
            connection = sqlite3.connect("database.sqlite")
            connection.execute("PRAGMA foreign_keys = ON")

            # When you extract the entities from SQLite columns, they come as a tuple. This code turns it into a regular list of bank names. It also removes any duplicates at the end.
            bankNamesTuple = connection.execute("SELECT BankName FROM BankDetails").fetchall()
            bankNames = []
            for balancesTuple in bankNamesTuple:
                bankNames.append(balancesTuple[0])

            st.text("")
            option = st.selectbox("Select the bank you're considering:", bankNames)

            if option:
                # This code compares the user-inputted balance range and finds the associated interest rate for the bank they picked.
                balanceRangesTuple = connection.execute(
                    "SELECT BalanceLowRange, BalanceHighRange FROM BalanceRanges WHERE BalanceRangeID IN (SELECT BalanceRangeID FROM InterestRates WHERE BankCurrencyID IN (SELECT BankCurrencyID FROM BankCurrency WHERE BankID IN (SELECT BankID FROM BankDetails WHERE BankName = ?)))",
                    (option,)).fetchall()
                balanceRanges = []
                for balancesTuple in balanceRangesTuple:
                    for i in balancesTuple:
                        balanceRanges.append(i)

                balanceRanges_updated = balanceRanges.copy()
                for i in range(1, len(balanceRanges_updated), 2):
                    if balanceRanges_updated[i] == 0:
                        balanceRanges_updated[i] = float("inf")

                for i in range(0, len(balanceRanges_updated), 2):
                    if balanceRanges_updated[i] <= num <= balanceRanges_updated[i + 1]:
                        interestRate = connection.execute(
                                "SELECT InterestRate FROM InterestRates WHERE BankCurrencyID = (SELECT BankCurrencyID FROM BankCurrency WHERE BankID = (SELECT BankID FROM BankDetails WHERE BankName = ?)) AND BalanceRangeID = (SELECT BalanceRangeID FROM BalanceRanges WHERE BalanceLowRange = ? AND BalanceHighRange = ?)",
                                (option, balanceRanges[i], balanceRanges[i + 1])).fetchall()[0][0]
                        break

                _, interestCol, _ = st.columns([4, 7, 4])

                with interestCol:
                    st.write("")
                    st.write("")
                    st.write("##### Your savings interest rate is:", interestRate)
            connection.close()
