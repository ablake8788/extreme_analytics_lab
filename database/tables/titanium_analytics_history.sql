/* ============================================================================
   Titanium Analytics - Extreme & Change Analytics Lab
   REPORT HISTORY DATABASE (Microsoft SQL Server 2016 or newer)

   Keeps everything needed to recreate any report later:

     ETL  raw sensor file  (e.g. Jensen_Beach_AHU1_temperature.xlsx)
          ta.SourceFile      the original file, byte for byte
          stg.RawReading     rows as text, exactly as read from the file
          ta.RawReading      typed readings (UTC + local time, Day/Night, value)

     ELT  analysis results (e.g. extreme_results_20250801-20260925.csv)
          ta.AnalysisRun     who/when/which file/which parameters/app build
          ta.ResultFile      the results CSV, byte for byte
          stg.AnalysisResult the CSV rows as text (loaded as-is)
          ta.AnalysisResult  typed results, transformed inside SQL

     REPORTS
          ta.ReferenceDocument  versions of Titanium_analytics.docx
          ta.Report             each Word report + the facts it was built from

   Recreate later:
     original raw file ......... ta.SourceFile.FileContent
     raw rows in file layout ... ta.vw_RawReading_SourceLayout
     results CSV ............... ta.ResultFile.FileContent, or ta.vw_AnalysisResult_CsvLayout
     re-run the analysis ....... parameters in ta.AnalysisRun (+ readings)
     Word report ............... ta.Report.ReportContent (or regenerate from FactsJson)

   Run this whole script once in SSMS or Azure Data Studio. It is safe to run
   again: tables are created only if missing, views/procedures are replaced.
   ============================================================================ */

-- Optional: create the database first
-- CREATE DATABASE TitaniumAnalytics;
-- GO
-- USE TitaniumAnalytics;
-- GO

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF SCHEMA_ID(N'ta')  IS NULL EXEC (N'CREATE SCHEMA ta');   -- core, typed history
GO
IF SCHEMA_ID(N'stg') IS NULL EXEC (N'CREATE SCHEMA stg');  -- staging, text as loaded
GO

/* ============================================================================
   1. REFERENCE: sites and sensors
   ============================================================================ */
IF OBJECT_ID(N'ta.Site', N'U') IS NULL
CREATE TABLE ta.Site (
    SiteId          INT IDENTITY(1,1)  NOT NULL CONSTRAINT PK_Site PRIMARY KEY,
    SiteName        NVARCHAR(100)      NOT NULL,              -- 'Jensen Beach'
    Timezone        VARCHAR(64)        NOT NULL,              -- 'America/New_York'
    Notes           NVARCHAR(500)      NULL,
    CreatedAtUtc    DATETIME2(0)       NOT NULL CONSTRAINT DF_Site_Created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_Site_Name UNIQUE (SiteName)
);
GO

IF OBJECT_ID(N'ta.Sensor', N'U') IS NULL
CREATE TABLE ta.Sensor (
    SensorId        INT IDENTITY(1,1)  NOT NULL CONSTRAINT PK_Sensor PRIMARY KEY,
    SiteId          INT                NOT NULL CONSTRAINT FK_Sensor_Site REFERENCES ta.Site (SiteId),
    EquipmentName   NVARCHAR(100)      NOT NULL,              -- 'AHU 1'
    ChannelName     NVARCHAR(150)      NOT NULL,              -- 'AHU 1 (channel 0)'  (column header in the file)
    Measurement     NVARCHAR(50)       NOT NULL,              -- 'Temperature'
    UnitName        NVARCHAR(30)       NULL,                  -- 'Fahrenheit'         (units row in the file)
    UnitSymbol      NVARCHAR(10)       NULL,                  -- N'°F'
    IsActive        BIT                NOT NULL CONSTRAINT DF_Sensor_Active DEFAULT 1,
    CreatedAtUtc    DATETIME2(0)       NOT NULL CONSTRAINT DF_Sensor_Created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_Sensor_Channel UNIQUE (SiteId, ChannelName)
);
GO

/* ============================================================================
   2. ETL - RAW SENSOR FILE
   ============================================================================ */
IF OBJECT_ID(N'ta.SourceFile', N'U') IS NULL
CREATE TABLE ta.SourceFile (
    SourceFileId     INT IDENTITY(1,1)  NOT NULL CONSTRAINT PK_SourceFile PRIMARY KEY,
    SensorId         INT                NOT NULL CONSTRAINT FK_SourceFile_Sensor REFERENCES ta.Sensor (SensorId),
    FileName         NVARCHAR(260)      NOT NULL,             -- 'Jensen_Beach_AHU1_temperature.xlsx'
    FileExtension    VARCHAR(10)        NOT NULL,             -- '.xlsx' '.xlsm' '.csv'
    SheetName        NVARCHAR(128)      NULL,                 -- 'Sheet1'
    FileSizeBytes    BIGINT             NOT NULL,
    FileSha256       BINARY(32)         NOT NULL,             -- same file is never stored twice
    FileContent      VARBINARY(MAX)     NOT NULL,             -- the original file, byte for byte
    HeaderJson       NVARCHAR(MAX)      NULL,                 -- column headers + units row as read
    ReadingCount     INT                NULL,
    FirstReadingUtc  DATETIME2(0)       NULL,
    LastReadingUtc   DATETIME2(0)       NULL,
    LoadStatus       VARCHAR(20)        NOT NULL CONSTRAINT DF_SourceFile_Status DEFAULT 'Staged',
    LoadMessage      NVARCHAR(1000)     NULL,
    LoadedAtUtc      DATETIME2(0)       NOT NULL CONSTRAINT DF_SourceFile_Loaded DEFAULT SYSUTCDATETIME(),
    LoadedBy         NVARCHAR(128)      NOT NULL CONSTRAINT DF_SourceFile_By DEFAULT SUSER_SNAME(),
    CONSTRAINT UQ_SourceFile_Sha UNIQUE (FileSha256),
    CONSTRAINT CK_SourceFile_Status CHECK (LoadStatus IN ('Staged', 'Loaded', 'Failed')),
    CONSTRAINT CK_SourceFile_Header CHECK (HeaderJson IS NULL OR ISJSON(HeaderJson) = 1)
);
GO

-- Rows exactly as read from the file (all text). Filled by the app, then
-- ta.usp_LoadRawReadings types them into ta.RawReading.
IF OBJECT_ID(N'stg.RawReading', N'U') IS NULL
CREATE TABLE stg.RawReading (
    SourceFileId     INT                NOT NULL,
    SourceRowNumber  INT                NOT NULL,             -- data row number in the file (1 = first reading)
    DateText         NVARCHAR(30)       NULL,                 -- 'Date'            e.g. '08/01/2025' or '2025-08-01 00:00:00'
    TimeText         NVARCHAR(20)       NULL,                 -- 'Time'            e.g. '11:29:27'
    TimezoneText     NVARCHAR(64)       NULL,                 -- 'Timezone'        e.g. 'America/New_York'
    EpochText        NVARCHAR(20)       NULL,                 -- 'Timestamp (UTC)' e.g. '1754062167'
    DayNightText     NVARCHAR(10)       NULL,                 -- 'Day/Night'
    ValueText        NVARCHAR(40)       NULL,                 -- 'AHU 1 (channel 0)' e.g. '73.2236'
    StagedAtUtc      DATETIME2(0)       NOT NULL CONSTRAINT DF_stgRaw_Staged DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_stgRawReading PRIMARY KEY (SourceFileId, SourceRowNumber)
);
GO

IF OBJECT_ID(N'ta.RawReading', N'U') IS NULL
CREATE TABLE ta.RawReading (
    RawReadingId     BIGINT IDENTITY(1,1) NOT NULL,
    SourceFileId     INT                NOT NULL CONSTRAINT FK_RawReading_File REFERENCES ta.SourceFile (SourceFileId),
    SensorId         INT                NOT NULL CONSTRAINT FK_RawReading_Sensor REFERENCES ta.Sensor (SensorId),
    SourceRowNumber  INT                NOT NULL,
    EpochSeconds     BIGINT             NULL,                 -- 'Timestamp (UTC)' as in the file
    TimestampUtc     DATETIME2(0)       NULL,                 -- from EpochSeconds
    LocalDate        DATE               NOT NULL,             -- 'Date'
    LocalTime        TIME(0)            NOT NULL,             -- 'Time'
    LocalTimestamp   DATETIME2(0)       NOT NULL,             -- Date + Time (what the app calls DateTime)
    Timezone         VARCHAR(64)        NULL,
    DayNight         VARCHAR(10)        NULL,
    Value            DECIMAL(12,4)      NOT NULL,             -- 4 decimals, as in the file
    CONSTRAINT PK_RawReading PRIMARY KEY CLUSTERED (SourceFileId, SourceRowNumber),
    CONSTRAINT UQ_RawReading_Id UNIQUE NONCLUSTERED (RawReadingId),
    CONSTRAINT CK_RawReading_DayNight CHECK (DayNight IS NULL OR DayNight IN ('Day', 'Night'))
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_RawReading_Sensor_Utc')
    CREATE INDEX IX_RawReading_Sensor_Utc ON ta.RawReading (SensorId, TimestampUtc) INCLUDE (Value, DayNight, LocalTimestamp);
GO

/* ============================================================================
   3. REFERENCE DOCUMENTS (Titanium_analytics.docx versions)
   ============================================================================ */
IF OBJECT_ID(N'ta.ReferenceDocument', N'U') IS NULL
CREATE TABLE ta.ReferenceDocument (
    ReferenceDocumentId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ReferenceDocument PRIMARY KEY,
    FileName         NVARCHAR(260)      NOT NULL,
    FileSha256       BINARY(32)         NOT NULL,
    FileContent      VARBINARY(MAX)     NOT NULL,
    ExtractedText    NVARCHAR(MAX)      NULL,                 -- the text the AI was given
    AddedAtUtc       DATETIME2(0)       NOT NULL CONSTRAINT DF_RefDoc_Added DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_ReferenceDocument_Sha UNIQUE (FileSha256)
);
GO

/* ============================================================================
   4. ELT - ANALYSIS RUNS AND RESULTS
   ============================================================================ */
IF OBJECT_ID(N'ta.AnalysisRun', N'U') IS NULL
CREATE TABLE ta.AnalysisRun (
    AnalysisRunId       INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_AnalysisRun PRIMARY KEY,
    SourceFileId        INT            NOT NULL CONSTRAINT FK_Run_SourceFile REFERENCES ta.SourceFile (SourceFileId),
    SensorId            INT            NOT NULL CONSTRAINT FK_Run_Sensor REFERENCES ta.Sensor (SensorId),
    SheetName           NVARCHAR(128)  NULL,
    TimestampColumn     NVARCHAR(150)  NULL,                  -- 'DateTime'
    ValueColumn         NVARCHAR(150)  NOT NULL,              -- 'AHU 1 (channel 0) [Fahrenheit]'
    DateFrom            DATETIME2(0)   NULL,                  -- From / To time period (local time)
    DateTo              DATETIME2(0)   NULL,
    -- Extreme channel
    BaselineMethod      VARCHAR(20)    NOT NULL,              -- bollinger, ewma, percentile, iqr, mad
    WindowSize          INT            NOT NULL,              -- e.g. 96
    EwmaAlpha           DECIMAL(9,4)   NULL,
    K_E                 DECIMAL(9,4)   NULL,
    K_P                 DECIMAL(9,4)   NULL,
    N_P                 INT            NULL,
    N_M                 INT            NULL,
    K_M                 DECIMAL(9,4)   NULL,
    N_Exit              INT            NULL,
    PercentileP         DECIMAL(9,4)   NULL,
    K_IQR               DECIMAL(9,4)   NULL,
    -- Change channel
    RocWindow           INT            NULL,
    RocBaselineWindow   INT            NULL,
    RocK                DECIMAL(9,4)   NULL,
    FrequencyWindow     INT            NULL,
    FrequencyMinCount   INT            NULL,
    -- Materiality weights
    W_Magnitude         DECIMAL(9,4)   NULL,
    W_Duration          DECIMAL(9,4)   NULL,
    W_Frequency         DECIMAL(9,4)   NULL,
    ParametersJson      NVARCHAR(MAX)  NULL,                  -- everything the app sent, for exact re-runs
    SummaryJson         NVARCHAR(MAX)  NULL,                  -- the app's result summary
    ResultRowCount      INT            NULL,
    AppBuild            INT            NULL,                  -- build number from the badge
    AppVersion          VARCHAR(20)    NULL,                  -- '1.0.12'
    GitCommit           VARCHAR(40)    NULL,
    RunAtUtc            DATETIME2(0)   NOT NULL CONSTRAINT DF_Run_At DEFAULT SYSUTCDATETIME(),
    RunBy               NVARCHAR(128)  NOT NULL CONSTRAINT DF_Run_By DEFAULT SUSER_SNAME(),
    Status              VARCHAR(20)    NOT NULL CONSTRAINT DF_Run_Status DEFAULT 'Created',
    CONSTRAINT CK_Run_Status CHECK (Status IN ('Created', 'ResultsLoaded', 'Failed')),
    CONSTRAINT CK_Run_Params  CHECK (ParametersJson IS NULL OR ISJSON(ParametersJson) = 1),
    CONSTRAINT CK_Run_Summary CHECK (SummaryJson IS NULL OR ISJSON(SummaryJson) = 1),
    CONSTRAINT CK_Run_Period  CHECK (DateFrom IS NULL OR DateTo IS NULL OR DateFrom <= DateTo)
);
GO

-- The results CSV file itself (keep the csv file)
IF OBJECT_ID(N'ta.ResultFile', N'U') IS NULL
CREATE TABLE ta.ResultFile (
    ResultFileId     INT IDENTITY(1,1)  NOT NULL CONSTRAINT PK_ResultFile PRIMARY KEY,
    AnalysisRunId    INT                NOT NULL CONSTRAINT FK_ResultFile_Run REFERENCES ta.AnalysisRun (AnalysisRunId),
    FileName         NVARCHAR(260)      NOT NULL,             -- 'extreme_results_20250801-20260925.csv'
    Scope            VARCHAR(10)        NOT NULL CONSTRAINT DF_ResultFile_Scope DEFAULT 'all',
    FileSizeBytes    BIGINT             NOT NULL,
    FileSha256       BINARY(32)         NOT NULL,
    FileContent      VARBINARY(MAX)     NOT NULL,             -- the CSV, byte for byte
    ResultRows         INT                NULL,
    LoadStatus       VARCHAR(20)        NOT NULL CONSTRAINT DF_ResultFile_Status DEFAULT 'Staged',
    LoadMessage      NVARCHAR(1000)     NULL,
    SavedAtUtc       DATETIME2(0)       NOT NULL CONSTRAINT DF_ResultFile_Saved DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_ResultFile_Sha UNIQUE (AnalysisRunId, FileSha256),
    CONSTRAINT CK_ResultFile_Scope  CHECK (Scope IN ('all', 'page', 'filtered')),
    CONSTRAINT CK_ResultFile_Status CHECK (LoadStatus IN ('Staged', 'Loaded', 'Failed'))
);
GO

-- The CSV rows loaded as-is (all text), same 30 columns as the file
IF OBJECT_ID(N'stg.AnalysisResult', N'U') IS NULL
CREATE TABLE stg.AnalysisResult (
    ResultFileId         INT            NOT NULL,
    SourceRowNumber      INT            NOT NULL,             -- data row in the CSV (1 = first)
    [Timestamp]          NVARCHAR(40)   NULL,
    [Value]              NVARCHAR(40)   NULL,
    AbnormalChangeFlag   NVARCHAR(10)   NULL,
    ConfirmedShiftFlag   NVARCHAR(10)   NULL,
    DeltaLower           NVARCHAR(40)   NULL,
    DeltaLower_pct       NVARCHAR(40)   NULL,
    DeltaUpper           NVARCHAR(40)   NULL,
    DeltaUpper_pct       NVARCHAR(40)   NULL,
    DeltaX               NVARCHAR(40)   NULL,
    EventEndTime         NVARCHAR(40)   NULL,
    EventStartTime       NVARCHAR(40)   NULL,
    ExtremeDirection     NVARCHAR(10)   NULL,
    ExtremeFlag          NVARCHAR(10)   NULL,
    FrequencyCount       NVARCHAR(20)   NULL,
    LowerLimit           NVARCHAR(40)   NULL,
    MaterialChangeFlag   NVARCHAR(10)   NULL,
    MaterialExtremeFlag  NVARCHAR(10)   NULL,
    MaterialityScore     NVARCHAR(40)   NULL,
    MeanZ_event          NVARCHAR(40)   NULL,
    MovingAverage        NVARCHAR(40)   NULL,
    PersistenceCount     NVARCHAR(20)   NULL,
    ROC                  NVARCHAR(40)   NULL,
    ROC_MeanBaseline     NVARCHAR(40)   NULL,
    ROC_StdDev           NVARCHAR(40)   NULL,
    ROC_ZScore           NVARCHAR(40)   NULL,
    RollingStdDev        NVARCHAR(40)   NULL,
    [State]              NVARCHAR(60)   NULL,
    UpperLimit           NVARCHAR(40)   NULL,
    ZScore               NVARCHAR(40)   NULL,
    [Day/Night]          NVARCHAR(10)   NULL,
    StagedAtUtc          DATETIME2(0)   NOT NULL CONSTRAINT DF_stgRes_Staged DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_stgAnalysisResult PRIMARY KEY (ResultFileId, SourceRowNumber)
);
GO

IF OBJECT_ID(N'ta.AnalysisResult', N'U') IS NULL
CREATE TABLE ta.AnalysisResult (
    AnalysisRunId        INT            NOT NULL CONSTRAINT FK_Result_Run REFERENCES ta.AnalysisRun (AnalysisRunId),
    RowNumber            INT            NOT NULL,
    ReadingTime          DATETIME2(0)   NOT NULL,             -- CSV 'Timestamp' (local time)
    Value                DECIMAL(12,4)  NOT NULL,
    DayNight             VARCHAR(10)    NULL,
    MovingAverage        FLOAT          NULL,
    RollingStdDev        FLOAT          NULL,
    UpperLimit           FLOAT          NULL,
    LowerLimit           FLOAT          NULL,
    ZScore               FLOAT          NULL,
    DeltaX               FLOAT          NULL,
    DeltaUpper           FLOAT          NULL,
    DeltaUpper_pct       FLOAT          NULL,
    DeltaLower           FLOAT          NULL,
    DeltaLower_pct       FLOAT          NULL,
    ExtremeFlag          BIT            NOT NULL,
    ExtremeDirection     VARCHAR(10)    NULL,
    [State]              VARCHAR(40)    NOT NULL,
    PersistenceCount     INT            NULL,
    EventStartTime       DATETIME2(0)   NULL,
    EventEndTime         DATETIME2(0)   NULL,
    MeanZ_event          FLOAT          NULL,
    ConfirmedShiftFlag   BIT            NOT NULL,
    MaterialExtremeFlag  BIT            NOT NULL,
    ROC                  FLOAT          NULL,
    ROC_MeanBaseline     FLOAT          NULL,
    ROC_StdDev           FLOAT          NULL,
    ROC_ZScore           FLOAT          NULL,
    AbnormalChangeFlag   BIT            NOT NULL,
    FrequencyCount       INT            NULL,
    MaterialChangeFlag   BIT            NOT NULL,
    MaterialityScore     FLOAT          NULL,
    CONSTRAINT PK_AnalysisResult PRIMARY KEY CLUSTERED (AnalysisRunId, RowNumber),
    CONSTRAINT CK_Result_DayNight  CHECK (DayNight IS NULL OR DayNight IN ('Day', 'Night')),
    CONSTRAINT CK_Result_Direction CHECK (ExtremeDirection IS NULL OR ExtremeDirection IN ('upper', 'lower', 'none'))
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_AnalysisResult_Run_Time')
    CREATE INDEX IX_AnalysisResult_Run_Time ON ta.AnalysisResult (AnalysisRunId, ReadingTime) INCLUDE (Value, [State], DayNight);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_AnalysisResult_NotNormal')
    CREATE INDEX IX_AnalysisResult_NotNormal ON ta.AnalysisResult (AnalysisRunId, [State], ReadingTime)
    WHERE [State] <> 'Normal';
GO

/* ============================================================================
   5. REPORTS
   ============================================================================ */
IF OBJECT_ID(N'ta.Report', N'U') IS NULL
CREATE TABLE ta.Report (
    ReportId             INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Report PRIMARY KEY,
    AnalysisRunId        INT            NOT NULL CONSTRAINT FK_Report_Run REFERENCES ta.AnalysisRun (AnalysisRunId),
    ResultFileId         INT            NULL     CONSTRAINT FK_Report_ResultFile REFERENCES ta.ResultFile (ResultFileId),
    ReferenceDocumentId  INT            NULL     CONSTRAINT FK_Report_RefDoc REFERENCES ta.ReferenceDocument (ReferenceDocumentId),
    FileName             NVARCHAR(260)  NOT NULL,             -- 'extreme_results_20250801-20251231.docx'
    LocationLabel        NVARCHAR(150)  NULL,                 -- 'Jensen Beach, AHU 1 (channel 0)'
    UnitsLabel           NVARCHAR(10)   NULL,                 -- N'°F'
    Scope                VARCHAR(10)    NOT NULL CONSTRAINT DF_Report_Scope DEFAULT 'all',
    PeriodStart          DATETIME2(0)   NULL,
    PeriodEnd            DATETIME2(0)   NULL,
    AISource             VARCHAR(20)    NOT NULL,             -- 'openai' or 'built-in'
    AIModel              VARCHAR(60)    NULL,                 -- 'gpt-4o-mini'
    AINote               NVARCHAR(500)  NULL,
    RemovedSentences     INT            NULL,                 -- AI sentences dropped by the number check
    FactsJson            NVARCHAR(MAX)  NULL,                 -- facts the report was built from
    ReportTextJson       NVARCHAR(MAX)  NULL,                 -- the wording used (AI or built-in)
    FileSizeBytes        BIGINT         NOT NULL,
    FileSha256           BINARY(32)     NOT NULL,
    ReportContent        VARBINARY(MAX) NOT NULL,             -- the .docx, byte for byte
    GeneratedAtUtc       DATETIME2(0)   NOT NULL CONSTRAINT DF_Report_Generated DEFAULT SYSUTCDATETIME(),
    GeneratedBy          NVARCHAR(128)  NOT NULL CONSTRAINT DF_Report_By DEFAULT SUSER_SNAME(),
    CONSTRAINT CK_Report_Scope  CHECK (Scope IN ('all', 'page', 'file')),
    CONSTRAINT CK_Report_Source CHECK (AISource IN ('openai', 'built-in')),
    CONSTRAINT CK_Report_Facts  CHECK (FactsJson IS NULL OR ISJSON(FactsJson) = 1),
    CONSTRAINT CK_Report_Text   CHECK (ReportTextJson IS NULL OR ISJSON(ReportTextJson) = 1)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Report_Run')
    CREATE INDEX IX_Report_Run ON ta.Report (AnalysisRunId, GeneratedAtUtc DESC);
GO

/* ============================================================================
   6. LOAD PROCEDURES
   ============================================================================ */

-- ETL step 2: stg.RawReading (text) -> ta.RawReading (typed)
CREATE OR ALTER PROCEDURE ta.usp_LoadRawReadings
    @SourceFileId INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @SensorId INT = (SELECT SensorId FROM ta.SourceFile WHERE SourceFileId = @SourceFileId);
    IF @SensorId IS NULL
        THROW 50001, 'Unknown SourceFileId.', 1;

    BEGIN TRANSACTION;

    DELETE FROM ta.RawReading WHERE SourceFileId = @SourceFileId;   -- re-runnable

    ;WITH typed AS (
        SELECT
            s.SourceRowNumber,
            -- Date: '08/01/2025' (MM/DD/YYYY) or '2025-08-01 00:00:00'
            COALESCE(TRY_CONVERT(date, s.DateText, 101),
                     TRY_CONVERT(date, LEFT(s.DateText, 10), 23))      AS LocalDate,
            TRY_CONVERT(time(0), s.TimeText)                          AS LocalTime,
            NULLIF(LTRIM(RTRIM(s.TimezoneText)), N'')                 AS Timezone,
            TRY_CONVERT(bigint, s.EpochText)                          AS EpochSeconds,
            NULLIF(LTRIM(RTRIM(s.DayNightText)), N'')                 AS DayNight,
            TRY_CONVERT(decimal(12,4), s.ValueText)                   AS Value
        FROM stg.RawReading AS s
        WHERE s.SourceFileId = @SourceFileId
    )
    INSERT INTO ta.RawReading
        (SourceFileId, SensorId, SourceRowNumber, EpochSeconds, TimestampUtc,
         LocalDate, LocalTime, LocalTimestamp, Timezone, DayNight, Value)
    SELECT
        @SourceFileId, @SensorId, t.SourceRowNumber, t.EpochSeconds,
        -- epoch seconds -> UTC (split into days + seconds: safe after 2038)
        CASE WHEN t.EpochSeconds IS NOT NULL THEN
            DATEADD(SECOND, CAST(t.EpochSeconds % 86400 AS int),
                    DATEADD(DAY, CAST(t.EpochSeconds / 86400 AS int), CAST('1970-01-01' AS datetime2(0))))
        END,
        t.LocalDate, t.LocalTime,
        DATEADD(SECOND, DATEDIFF(SECOND, CAST('00:00:00' AS time(0)), t.LocalTime), CAST(t.LocalDate AS datetime2(0))),
        t.Timezone, t.DayNight, t.Value
    FROM typed AS t
    WHERE t.LocalDate IS NOT NULL AND t.LocalTime IS NOT NULL AND t.Value IS NOT NULL;

    DECLARE @loaded INT = @@ROWCOUNT;
    DECLARE @staged INT = (SELECT COUNT(*) FROM stg.RawReading WHERE SourceFileId = @SourceFileId);

    UPDATE f SET
        ReadingCount    = @loaded,
        FirstReadingUtc = x.FirstUtc,
        LastReadingUtc  = x.LastUtc,
        LoadStatus      = 'Loaded',
        LoadMessage     = CONCAT(@loaded, N' of ', @staged, N' rows loaded',
                                 CASE WHEN @loaded < @staged THEN CONCAT(N'; ', @staged - @loaded, N' rejected (bad date/time/value)') END)
    FROM ta.SourceFile AS f
    CROSS APPLY (SELECT MIN(TimestampUtc) AS FirstUtc, MAX(TimestampUtc) AS LastUtc
                 FROM ta.RawReading WHERE SourceFileId = @SourceFileId) AS x
    WHERE f.SourceFileId = @SourceFileId;

    DELETE FROM stg.RawReading WHERE SourceFileId = @SourceFileId;   -- staging is temporary

    COMMIT TRANSACTION;

    SELECT @SourceFileId AS SourceFileId, @staged AS StagedRows, @loaded AS LoadedRows,
           @staged - @loaded AS RejectedRows;
END;
GO

-- ELT step 2: stg.AnalysisResult (CSV as text) -> ta.AnalysisResult (typed)
CREATE OR ALTER PROCEDURE ta.usp_LoadAnalysisResults
    @ResultFileId INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @RunId INT = (SELECT AnalysisRunId FROM ta.ResultFile WHERE ResultFileId = @ResultFileId);
    IF @RunId IS NULL
        THROW 50002, 'Unknown ResultFileId.', 1;

    BEGIN TRANSACTION;

    DELETE FROM ta.AnalysisResult WHERE AnalysisRunId = @RunId;     -- re-runnable

    INSERT INTO ta.AnalysisResult
        (AnalysisRunId, RowNumber, ReadingTime, Value, DayNight,
         MovingAverage, RollingStdDev, UpperLimit, LowerLimit, ZScore,
         DeltaX, DeltaUpper, DeltaUpper_pct, DeltaLower, DeltaLower_pct,
         ExtremeFlag, ExtremeDirection, [State], PersistenceCount,
         EventStartTime, EventEndTime, MeanZ_event, ConfirmedShiftFlag, MaterialExtremeFlag,
         ROC, ROC_MeanBaseline, ROC_StdDev, ROC_ZScore,
         AbnormalChangeFlag, FrequencyCount, MaterialChangeFlag, MaterialityScore)
    SELECT
        @RunId,
        s.SourceRowNumber,
        TRY_CONVERT(datetime2(0), LEFT(s.[Timestamp], 19), 120),
        TRY_CONVERT(decimal(12,4), s.[Value]),
        NULLIF(s.[Day/Night], N''),
        TRY_CONVERT(float, s.MovingAverage),
        TRY_CONVERT(float, s.RollingStdDev),
        TRY_CONVERT(float, s.UpperLimit),
        TRY_CONVERT(float, s.LowerLimit),
        TRY_CONVERT(float, s.ZScore),
        TRY_CONVERT(float, s.DeltaX),
        TRY_CONVERT(float, s.DeltaUpper),
        TRY_CONVERT(float, s.DeltaUpper_pct),
        TRY_CONVERT(float, s.DeltaLower),
        TRY_CONVERT(float, s.DeltaLower_pct),
        CASE WHEN s.ExtremeFlag         IN (N'True', N'true', N'1') THEN 1 ELSE 0 END,
        NULLIF(LOWER(s.ExtremeDirection), N''),
        COALESCE(NULLIF(s.[State], N''), N'Normal'),
        TRY_CONVERT(int, TRY_CONVERT(float, s.PersistenceCount)),
        TRY_CONVERT(datetime2(0), LEFT(NULLIF(s.EventStartTime, N''), 19), 120),
        TRY_CONVERT(datetime2(0), LEFT(NULLIF(s.EventEndTime, N''), 19), 120),
        TRY_CONVERT(float, s.MeanZ_event),
        CASE WHEN s.ConfirmedShiftFlag  IN (N'True', N'true', N'1') THEN 1 ELSE 0 END,
        CASE WHEN s.MaterialExtremeFlag IN (N'True', N'true', N'1') THEN 1 ELSE 0 END,
        TRY_CONVERT(float, s.ROC),
        TRY_CONVERT(float, s.ROC_MeanBaseline),
        TRY_CONVERT(float, s.ROC_StdDev),
        TRY_CONVERT(float, s.ROC_ZScore),
        CASE WHEN s.AbnormalChangeFlag  IN (N'True', N'true', N'1') THEN 1 ELSE 0 END,
        TRY_CONVERT(int, TRY_CONVERT(float, s.FrequencyCount)),
        CASE WHEN s.MaterialChangeFlag  IN (N'True', N'true', N'1') THEN 1 ELSE 0 END,
        TRY_CONVERT(float, s.MaterialityScore)
    FROM stg.AnalysisResult AS s
    WHERE s.ResultFileId = @ResultFileId
      AND TRY_CONVERT(datetime2(0), LEFT(s.[Timestamp], 19), 120) IS NOT NULL
      AND TRY_CONVERT(decimal(12,4), s.[Value]) IS NOT NULL;

    DECLARE @loaded INT = @@ROWCOUNT;
    DECLARE @staged INT = (SELECT COUNT(*) FROM stg.AnalysisResult WHERE ResultFileId = @ResultFileId);

    UPDATE ta.ResultFile
       SET ResultRows = @loaded, LoadStatus = 'Loaded',
           LoadMessage = CONCAT(@loaded, N' of ', @staged, N' rows loaded',
                                CASE WHEN @loaded < @staged THEN CONCAT(N'; ', @staged - @loaded, N' rejected') END)
     WHERE ResultFileId = @ResultFileId;

    UPDATE ta.AnalysisRun
       SET ResultRowCount = @loaded, Status = 'ResultsLoaded'
     WHERE AnalysisRunId = @RunId;

    DELETE FROM stg.AnalysisResult WHERE ResultFileId = @ResultFileId;

    COMMIT TRANSACTION;

    SELECT @RunId AS AnalysisRunId, @ResultFileId AS ResultFileId,
           @staged AS StagedRows, @loaded AS LoadedRows, @staged - @loaded AS RejectedRows;
END;
GO

/* ============================================================================
   7. VIEWS - RECREATE AND REVIEW
   ============================================================================ */

-- Raw readings in the same layout as the original file (export to recreate it)
CREATE OR ALTER VIEW ta.vw_RawReading_SourceLayout
AS
SELECT
    r.SourceFileId,
    r.SourceRowNumber,
    CONVERT(char(10), r.LocalDate, 101)        AS [Date],              -- MM/DD/YYYY
    CONVERT(char(8),  r.LocalTime, 108)        AS [Time],              -- hh:mm:ss
    r.Timezone                                 AS [Timezone],
    r.EpochSeconds                             AS [Timestamp (UTC)],   -- seconds
    r.DayNight                                 AS [Day/Night],
    r.Value                                    AS [Value],             -- header: Sensor.ChannelName, units row: Sensor.UnitName
    s.ChannelName                              AS ValueColumnName,
    s.UnitName                                 AS ValueUnits
FROM ta.RawReading AS r
JOIN ta.Sensor     AS s ON s.SensorId = r.SensorId;
GO

-- One reading per sensor and time across all uploads (newest upload wins)
CREATE OR ALTER VIEW ta.vw_Reading
AS
SELECT SensorId, TimestampUtc, LocalTimestamp, DayNight, Value, SourceFileId
FROM (
    SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.SensorId, COALESCE(r.TimestampUtc, r.LocalTimestamp)
                                   ORDER BY r.SourceFileId DESC) AS rn
    FROM ta.RawReading AS r
) AS x
WHERE rn = 1;
GO

-- Results in the same column order as the app's results CSV
CREATE OR ALTER VIEW ta.vw_AnalysisResult_CsvLayout
AS
SELECT
    a.AnalysisRunId,
    a.RowNumber,
    CONVERT(varchar(19), a.ReadingTime, 120)                       AS [Timestamp],
    a.Value                                                        AS [Value],
    CASE a.AbnormalChangeFlag  WHEN 1 THEN 'true' ELSE 'false' END AS AbnormalChangeFlag,
    CASE a.ConfirmedShiftFlag  WHEN 1 THEN 'true' ELSE 'false' END AS ConfirmedShiftFlag,
    a.DeltaLower, a.DeltaLower_pct, a.DeltaUpper, a.DeltaUpper_pct, a.DeltaX,
    CONVERT(varchar(19), a.EventEndTime, 120)                      AS EventEndTime,
    CONVERT(varchar(19), a.EventStartTime, 120)                    AS EventStartTime,
    a.ExtremeDirection,
    CASE a.ExtremeFlag         WHEN 1 THEN 'true' ELSE 'false' END AS ExtremeFlag,
    a.FrequencyCount, a.LowerLimit,
    CASE a.MaterialChangeFlag  WHEN 1 THEN 'true' ELSE 'false' END AS MaterialChangeFlag,
    CASE a.MaterialExtremeFlag WHEN 1 THEN 'true' ELSE 'false' END AS MaterialExtremeFlag,
    a.MaterialityScore, a.MeanZ_event, a.MovingAverage, a.PersistenceCount,
    a.ROC, a.ROC_MeanBaseline, a.ROC_StdDev, a.ROC_ZScore, a.RollingStdDev,
    a.[State], a.UpperLimit, a.ZScore,
    a.DayNight                                                     AS [Day/Night]
FROM ta.AnalysisResult AS a;
GO

-- History overview: one line per analysis run
CREATE OR ALTER VIEW ta.vw_RunHistory
AS
SELECT
    ar.AnalysisRunId,
    ar.RunAtUtc,
    ar.RunBy,
    si.SiteName,
    se.ChannelName,
    sf.FileName                    AS SourceFileName,
    sf.ReadingCount                AS SourceReadings,
    ar.DateFrom, ar.DateTo,
    ar.BaselineMethod, ar.WindowSize, ar.K_E,
    ar.ResultRowCount,
    ar.AppBuild, ar.AppVersion,
    ar.Status,
    (SELECT COUNT(*) FROM ta.ResultFile rf WHERE rf.AnalysisRunId = ar.AnalysisRunId) AS ResultFiles,
    (SELECT COUNT(*) FROM ta.Report rp WHERE rp.AnalysisRunId = ar.AnalysisRunId)     AS Reports,
    (SELECT TOP (1) rp.FileName FROM ta.Report rp
      WHERE rp.AnalysisRunId = ar.AnalysisRunId ORDER BY rp.GeneratedAtUtc DESC)     AS LatestReport,
    (SELECT COUNT(*) FROM ta.AnalysisResult x
      WHERE x.AnalysisRunId = ar.AnalysisRunId AND x.ExtremeFlag = 1)                 AS ExtremeReadings
FROM ta.AnalysisRun AS ar
JOIN ta.SourceFile  AS sf ON sf.SourceFileId = ar.SourceFileId
JOIN ta.Sensor      AS se ON se.SensorId = ar.SensorId
JOIN ta.Site        AS si ON si.SiteId = se.SiteId;
GO

/* ============================================================================
   8. STARTER DATA - Jensen Beach AHU 1
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM ta.Site WHERE SiteName = N'Jensen Beach')
    INSERT INTO ta.Site (SiteName, Timezone) VALUES (N'Jensen Beach', 'America/New_York');

IF NOT EXISTS (SELECT 1 FROM ta.Sensor se JOIN ta.Site si ON si.SiteId = se.SiteId
               WHERE si.SiteName = N'Jensen Beach' AND se.ChannelName = N'AHU 1 (channel 0)')
    INSERT INTO ta.Sensor (SiteId, EquipmentName, ChannelName, Measurement, UnitName, UnitSymbol)
    SELECT SiteId, N'AHU 1', N'AHU 1 (channel 0)', N'Temperature', N'Fahrenheit', N'°F'
    FROM ta.Site WHERE SiteName = N'Jensen Beach';
GO

/* ============================================================================
   USAGE (what the app will do; shown here for manual loads and checks)

   ETL - raw file
     1. INSERT ta.SourceFile (SensorId, FileName, FileExtension, SheetName,
        FileSizeBytes, FileSha256, FileContent, HeaderJson)      -> SourceFileId
     2. bulk insert the rows as text into stg.RawReading
     3. EXEC ta.usp_LoadRawReadings @SourceFileId = <id>;

   ELT - results
     4. INSERT ta.AnalysisRun (... parameters ...)                -> AnalysisRunId
     5. INSERT ta.ResultFile  (AnalysisRunId, FileName, ..., FileContent) -> ResultFileId
     6. bulk insert the CSV rows as text into stg.AnalysisResult
     7. EXEC ta.usp_LoadAnalysisResults @ResultFileId = <id>;

   Report
     8. INSERT ta.Report (AnalysisRunId, ResultFileId, ReferenceDocumentId,
        FileName, ..., FactsJson, ReportContent)

   Checks
     SELECT * FROM ta.vw_RunHistory ORDER BY RunAtUtc DESC;
     SELECT LoadStatus, LoadMessage FROM ta.SourceFile;
     SELECT TOP (10) * FROM ta.vw_RawReading_SourceLayout WHERE SourceFileId = 1 ORDER BY SourceRowNumber;
     SELECT TOP (10) * FROM ta.vw_AnalysisResult_CsvLayout WHERE AnalysisRunId = 1 ORDER BY RowNumber;
   ============================================================================ */
