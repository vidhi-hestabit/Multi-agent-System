CHINOOK_SCHEMA: str = """
Tables:
- Artist(ArtistId, Name)
- Album(AlbumId, Title, ArtistId)
- Track(TrackId, Name, AlbumId, MediaTypeId, GenreId, Composer, Milliseconds, Bytes, UnitPrice)
- Genre(GenreId, Name)
- MediaType(MediaTypeId, Name)
- Playlist(PlaylistId, Name)
- PlaylistTrack(PlaylistId, TrackId)
- Employee(EmployeeId, LastName, FirstName, Title, ReportsTo, BirthDate, HireDate, Address, City, State, Country, PostalCode, Phone, Fax, Email)
- Customer(CustomerId, FirstName, LastName, Company, Address, City, State, Country, PostalCode, Phone, Fax, Email, SupportRepId)
- Invoice(InvoiceId, CustomerId, InvoiceDate, BillingAddress, BillingCity, BillingState, BillingCountry, BillingPostalCode, Total)
- InvoiceItem(InvoiceLineId, InvoiceId, TrackId, UnitPrice, Quantity)
"""

SQL_GENERATION_SYSTEM: str = f"""You are a SQLite SQL expert. Given a natural language question, return ONLY a valid SQLite SQL query. No explanation, no markdown fences.

Schema:
{CHINOOK_SCHEMA}
"""

SQL_ANSWER_SYSTEM: str = """You are a helpful assistant that explains database query results in plain, friendly English.

Given the original user question and the raw query results, write a single clear sentence or short paragraph that directly answers the question.

Rules:
- Never show SQL, column names, or raw dict/JSON to the user.
- If the result is a count, state the number naturally (e.g. "AC/DC has 2 albums").
- If the result is a list, summarise it concisely (e.g. "The 11 tables are: Album, Artist, ...").
- If there are no results, say so politely.
- Keep the answer short and conversational.
"""