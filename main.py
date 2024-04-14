# Importing packages I will need.
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from urllib.request import urlopen
import sqlite3


# Setting required variables
import os
import openai
apiKey = os.environ["OPENAI_API_KEY"]
openai.api_key = apiKey
model = "gpt-3.5-turbo"

from datetime import date
dateToday = date.today()


# Connecting to the database and creating a table if one doesn't already exist.
connection = sqlite3.connect("database.sqlite")
connection.execute(
    "CREATE TABLE IF NOT EXISTS data (num INTEGER PRIMARY KEY AUTOINCREMENT, bankName STRING, balanceLowerRange INTEGER, balanceUpperRange INTEGER, interestRate REAL, dateOfExtraction STRING);")


# Extracting the HTML code from the respective websites and placing each section into an array.
def findHTMLSections(url, lookThroughTables):
    html = urlopen(url).read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.find_all("section")
    if lookThroughTables == "yes":
        sections += soup.find_all("table")
    return sections


# Using the GPT API to determine if the sections of HTML code (in plaintext) include the interest rates we want.
def checkIfContainsInterestRates(sectionCheck, model):
    responseCheck = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "Your purpose is to inform if there are any balance ranges with corresponding AER interest rates for each range contained within the text given to you. Only answer with 'yes' or 'no'."},
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
def insertIntoDatabase(balanceInterests, bankName, connection):
    for i in range(0, len(balanceInterests) - 1, 3):
        connection.execute(
            "INSERT INTO data (bankName, balanceLowerRange, balanceUpperRange, interestRate, dateOfExtraction) VALUES (?, ?, ?, ?, ?)",
            (bankName, balanceInterests[i], balanceInterests[i + 1], balanceInterests[i + 2], dateToday))


# The main function that links all the other functions together, it extracts all the data and automatically inserts it into the database.
def getInterestRatesAndInsertIntoDatabase(info, model, connection, lookThroughTables="no"):
    sectionsOfHTML = findHTMLSections(info[0], lookThroughTables)
    for sectionCheck in sectionsOfHTML:
        sectionCheck = sectionCheck.get_text().strip().replace("\n", " ")
        yn = checkIfContainsInterestRates(sectionCheck, model)
        if "yes" in yn.lower():
            section = sectionCheck
            balanceInterests = getArrayOfBalanceInterests(section, model)
            insertIntoDatabase(balanceInterests, info[1], connection)
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
                # NatWest
                info = ["https://www.natwest.com/savings/flexible-saver.html", "NatWest"]
                getInterestRatesAndInsertIntoDatabase(info, model, connection)

                # Barclays
                info = ["https://www.barclays.co.uk/savings/interest-rates/everyday-saver/", "Barclays"]
                lookThroughTables = "yes"
                getInterestRatesAndInsertIntoDatabase(info, model, connection, lookThroughTables)

                # HSBC
                info = ["https://www.hsbc.co.uk/savings/products/flexible-saver/", "HSBC"]
                lookThroughTables = "yes"
                getInterestRatesAndInsertIntoDatabase(info, model, connection, lookThroughTables)

                connection.commit()

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
    st.caption("The name of the SQLite table is 'data'")

    # Displaying the data in the table.
    if st.button("Display Table"):
        df = pd.read_sql_query("SELECT * FROM data", connection)
        st.dataframe(df)

    # Executing SQL Read Queries to display specific data from the table.
    readQuery = st.text_input("Enter a READ SQL query here:")

    if readQuery:
        connection = sqlite3.connect("database.sqlite")
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
        if writeQuery[0:6].lower() == "create":
            st.write("This is only for dealing with the table 'data'")
        else:
            try:
                connection.execute(writeQuery)
            except:
                st.write("Invalid Query")
            df = pd.read_sql_query("SELECT * FROM data", connection)
            st.dataframe(df)
            st.caption("(0 means infinite)")
            if st.button("Commit Changes to Database"):
                connection.commit()
                st.write("Changes committed successfully!")
        connection.close()

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

            # When you extract the entities from SQLite columns, they come as a tuple. This code turns it into a regular list of bank names. It also removes any duplicates at the end.
            bankNamesTuple = connection.execute("SELECT bankName FROM data").fetchall()
            bankNames = []
            for balancesTuple in bankNamesTuple:
                bankNames.append(balancesTuple[0])
            bankNames = list(set(bankNames))

            st.text("")
            option = st.selectbox(
                "Select the bank you're considering:", bankNames)

            if option:
                # This code compares the user-inputted balance range and finds the associated interest rate for the bank they picked.
                balanceRangesTuple = connection.execute(
                    "SELECT balanceLowerRange, balanceUpperRange FROM data WHERE bankName = ?", (option,)).fetchall()
                balanceRanges = []
                for balancesTuple in balanceRangesTuple:
                    for i in balancesTuple:
                        balanceRanges.append(i)

                for i in range(1, len(balanceRanges), 2):
                    if balanceRanges[i] == 0:
                        balanceRanges[i] = float("inf")

                interestRate = 0
                for i in range(0, len(balanceRanges), 2):
                    if balanceRanges[i] <= num <= balanceRanges[i + 1]:
                        interestRate = \
                            connection.execute(
                                "SELECT interestRate FROM data WHERE bankName = ? AND balanceLowerRange = ?",
                                (option, balanceRanges[i])).fetchall()[0][0]
                        break

                _, interestCol, _ = st.columns([4, 7, 4])

                with interestCol:
                    st.write("")
                    st.write("")
                    st.write("##### Your savings interest rate is:", interestRate)
