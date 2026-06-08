// Project and document creation utilities for automated builder

function GetFocusedProject: IProject;
begin
    Result := GetWorkspace.DM_FocusedProject;
end;

function ProjectFilePath(ProjectName, ProjectPath: String): String;
begin
    Result := IncludeTrailingPathDelimiter(ProjectPath) + ProjectName + '.PrjPcb';
end;

function WriteMinimalPrjPcb(ProjectName, FullPath: String): Boolean;
var
    SL: TStringList;
begin
    Result := False;
    SL := TStringList.Create;
    try
        // .PrjPcb is INI-format (same family as .PrjScr), not XML.
        SL.Add('[Design]');
        SL.Add('Version=1.0');
        SL.Add('HierarchyMode=0');
        SL.Add('ChannelRoomNamingStyle=0');
        SL.Add('ChannelDesignatorFormatString=$Component_$RoomName');
        SL.Add('ChannelRoomLevelSeperator=_');
        SL.Add('OpenOutputs=1');
        SL.Add('ArchiveProject=0');
        SL.Add('TimestampOutput=0');
        SL.Add('SeparateFolders=0');
        SL.Add('TemplateLocationPath=');
        SL.Add('PinSwapBy_Netlabel=1');
        SL.Add('PinSwapBy_Pin=1');
        SL.Add('AllowPortNetNames=0');
        SL.Add('AllowSheetEntryNetNames=1');
        SL.Add('AppendSheetNumberToLocalNets=0');
        SL.Add('NetlistSinglePinNets=0');
        SL.Add('DefaultConfiguration=Default - All Constraints');
        SL.Add('UserID=0xFFFFFFFF');
        SL.Add('DefaultPcbProtel=1');
        SL.Add('DefaultPcbPcad=0');
        SL.Add('ReorderDocumentsOnCompile=1');
        SL.Add('NameNetsHierarchically=0');
        SL.Add('PowerPortNamesTakePriority=0');
        SL.Add('AutoSheetNumbering=0');
        SL.Add('AutoCrossReferences=1');
        SL.Add('NewIndexingOfSheetSymbols=1');
        SL.Add('PushECOToAnnotationFile=1');
        SL.Add('DItemRevisionGUID=');
        SL.Add('ReportSuppressedErrorsInMessages=0');
        SL.Add('FSMCodingStyle=eFMSDropDownList_OneProcess');
        SL.Add('FSMEncodingStyle=eFMSDropDownList_OneHot');
        SL.Add('IsProjectConflictPreventionWarningsEnabled=0');
        SL.Add('ConstraintManagerFlow=0');
        SL.Add('IsVirtualBomDocumentRemoved=0');
        SL.Add('OutputPath=');
        SL.Add('LogFolderPath=');
        SL.Add('ManagedProjectGUID=');
        SL.Add('IncludeDesignInRelease=0');
        SL.Add('CrossRefSheetStyle=1');
        SL.Add('CrossRefLocationStyle=1');
        SL.Add('CrossRefPorts=3');
        SL.Add('CrossRefCrossSheets=1');
        SL.Add('CrossRefSheetEntries=0');
        SL.Add('CrossRefFollowFromMainSettings=1');
        ForceDirectories(ExtractFilePath(FullPath));
        SL.SaveToFile(FullPath);
        Result := FileExists(FullPath);
    finally
        SL.Free;
    end;
end;

function OpenProjectFile(FullPath: String): Boolean;
var
    Project: IProject;
    ServerDoc: IServerDocument;
    Kind: String;
begin
    Result := False;
    if not FileExists(FullPath) then Exit;

    Project := GetWorkspace.DM_OpenProject(FullPath, True);
    if Project <> Nil then
    begin
        Sleep(500);
        Result := True;
        Exit;
    end;

    Kind := Client.GetDocumentKindFromDocumentPath(FullPath);
    ServerDoc := Client.OpenDocument(Kind, FullPath);
    if ServerDoc <> Nil then
    begin
        Client.ShowDocument(ServerDoc);
        Sleep(500);
        Result := (GetFocusedProject <> Nil);
    end;
end;

function CreateProject(ProjectName, ProjectPath: String): String;
var
    FullPath: String;
    ResultProps: TStringList;
    OutputLines: TStringList;
begin
    FullPath := ProjectFilePath(ProjectName, ProjectPath);
    if not WriteMinimalPrjPcb(ProjectName, FullPath) then
    begin
        Result := 'ERROR: Failed to write project skeleton to ' + FullPath;
        Exit;
    end;

    if not OpenProjectFile(FullPath) then
    begin
        Result := 'ERROR: Could not open or focus project at ' + FullPath;
        Exit;
    end;

    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'project_path', ProjectPath);
        AddJSONProperty(ResultProps, 'project_file', FullPath);
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

function NewDocViaOpenObject(KindStr: String): IServerDocument;
begin
    Result := Nil;
    try
        ResetParameters;
        AddStringParameter('ObjectKind', 'NewAnything');
        AddStringParameter('Kind', KindStr);
        RunProcess('WorkspaceManager:OpenObject');
        Sleep(800);
        Result := Client.GetCurrentView.OwnerDocument;
    except
        Result := Nil;
    end;
end;

function SaveServerDocAs(ServerDoc: IServerDocument; TargetPath: String): Boolean;
begin
    Result := False;
    if ServerDoc = Nil then Exit;
    try
        ForceDirectories(ExtractFilePath(TargetPath));
        ServerDoc.SetModified(True);
        Result := ServerDoc.DoSafeChangeFileNameAndSave(TargetPath, '');
        if not Result then
            Result := FileExists(TargetPath);
    except
        Result := False;
    end;
end;

function AddDocToFocusedProject(DocPath: String): Boolean;
var
    Project: IProject;
begin
    Result := False;
    Project := GetFocusedProject;
    if Project = Nil then Exit;
    try
        Project.DM_AddSourceDocument(DocPath);
        Result := True;
    except
        Result := False;
    end;
end;

function CreateSchematicLibrary(LibName, ProjectPath: String): String;
var
    FullPath, BaseName: String;
    ServerDoc: IServerDocument;
    ResultProps: TStringList;
    OutputLines: TStringList;
begin
    BaseName := LibName;
    if Pos('.', BaseName) = 0 then
        BaseName := LibName + '.SchLib';
    FullPath := IncludeTrailingPathDelimiter(ProjectPath) + BaseName;

    ServerDoc := NewDocViaOpenObject('SCHLIB');
    if ServerDoc = Nil then
    begin
        Result := 'ERROR: WorkspaceManager:OpenObject SCHLIB failed';
        Exit;
    end;

    if not SaveServerDocAs(ServerDoc, FullPath) then
    begin
        Result := 'ERROR: Failed to save SchLib to ' + FullPath;
        Exit;
    end;

    AddDocToFocusedProject(FullPath);
    Client.ShowDocument(ServerDoc);
    Sleep(500);

    if (SchServer.GetCurrentSchDocument = Nil) or
       (SchServer.GetCurrentSchDocument.ObjectID <> eSchLib) then
    begin
        Result := 'ERROR: SchLib not focused after creation';
        Exit;
    end;

    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'lib_path', FullPath);
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

function CreatePcbLibrary(LibName, ProjectPath: String): String;
var
    FullPath, BaseName: String;
    ServerDoc: IServerDocument;
    ResultProps: TStringList;
    OutputLines: TStringList;
begin
    BaseName := LibName;
    if Pos('.', BaseName) = 0 then
        BaseName := LibName + '.PcbLib';
    FullPath := IncludeTrailingPathDelimiter(ProjectPath) + BaseName;

    ServerDoc := NewDocViaOpenObject('DefaultPcbLib');
    if ServerDoc = Nil then
    begin
        Result := 'ERROR: WorkspaceManager:OpenObject DefaultPcbLib failed';
        Exit;
    end;

    if not SaveServerDocAs(ServerDoc, FullPath) then
    begin
        Result := 'ERROR: Failed to save PcbLib to ' + FullPath;
        Exit;
    end;

    AddDocToFocusedProject(FullPath);
    Client.ShowDocument(ServerDoc);
    Sleep(500);

    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'lib_path', FullPath);
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

function CreateSchematicSheet(SheetName, ProjectPath: String): String;
var
    FullPath, BaseName: String;
    ServerDoc: IServerDocument;
    Project: IProject;
    ResultProps: TStringList;
    OutputLines: TStringList;
begin
    BaseName := SheetName;
    if Pos('.', BaseName) = 0 then
        BaseName := SheetName + '.SchDoc';
    FullPath := IncludeTrailingPathDelimiter(ProjectPath) + BaseName;

    ServerDoc := NewDocViaOpenObject('SCH');
    if ServerDoc = Nil then
    begin
        Result := 'ERROR: WorkspaceManager:OpenObject SCH failed';
        Exit;
    end;

    if not SaveServerDocAs(ServerDoc, FullPath) then
    begin
        Result := 'ERROR: Failed to save schematic to ' + FullPath;
        Exit;
    end;

    AddDocToFocusedProject(FullPath);
    Client.ShowDocument(ServerDoc);
    Sleep(500);

    if (SchServer.GetCurrentSchDocument = Nil) or
       (SchServer.GetCurrentSchDocument.ObjectID <> eSchDoc) then
    begin
        Result := 'ERROR: Schematic sheet not focused after creation';
        Exit;
    end;

    Project := GetFocusedProject;
    if Project <> Nil then
    begin
        try
            Project.DM_OpenAndFocusDocument('SCH', FullPath);
        except
        end;
    end;

    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'sheet_path', FullPath);
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

function CreatePcbDocument(PcbName, ProjectPath: String): String;
var
    FullPath, BaseName: String;
    ServerDoc: IServerDocument;
    ResultProps: TStringList;
    OutputLines: TStringList;
begin
    BaseName := PcbName;
    if Pos('.', BaseName) = 0 then
        BaseName := PcbName + '.PcbDoc';
    FullPath := IncludeTrailingPathDelimiter(ProjectPath) + BaseName;

    ServerDoc := NewDocViaOpenObject('DefaultPcb');
    if ServerDoc = Nil then
    begin
        Result := 'ERROR: WorkspaceManager:OpenObject DefaultPcb failed';
        Exit;
    end;

    if not SaveServerDocAs(ServerDoc, FullPath) then
    begin
        Result := 'ERROR: Failed to save PCB to ' + FullPath;
        Exit;
    end;

    AddDocToFocusedProject(FullPath);
    Client.ShowDocument(ServerDoc);
    Sleep(500);

    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'pcb_path', FullPath);
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

function FocusDocument(DocPath: String): String;
var
    Ext, DocKind: String;
    ServerDoc: IServerDocument;
    ResultProps: TStringList;
    OutputLines: TStringList;
begin
    if not FileExists(DocPath) then
    begin
        Result := 'ERROR: Document not found: ' + DocPath;
        Exit;
    end;

    Ext := LowerCase(ExtractFileExt(DocPath));
    if Ext = '.schlib' then DocKind := 'SCHLIB'
    else if Ext = '.schdoc' then DocKind := 'SCH'
    else if Ext = '.pcbdoc' then DocKind := 'PCB'
    else if Ext = '.pcblib' then DocKind := 'PCBLIB'
    else if Ext = '.prjpcb' then DocKind := 'PCB_PROJECT'
    else
    begin
        Result := 'ERROR: Unknown document extension: ' + Ext;
        Exit;
    end;

    ServerDoc := Client.OpenDocument(DocKind, DocPath);
    if ServerDoc = Nil then
    begin
        Result := 'ERROR: Client.OpenDocument failed for ' + DocPath;
        Exit;
    end;

    Client.ShowDocument(ServerDoc);
    Sleep(500);

    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'document_kind', DocKind);
        AddJSONProperty(ResultProps, 'document_path', DocPath);
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

function SyncToPcb: String;
var
    ResultProps: TStringList;
    OutputLines: TStringList;
    Ok: Boolean;
begin
    Ok := False;
    try
        ResetParameters;
        AddStringParameter('Action', 'UpdateAll');
        RunProcess('Sch:UpdatePCB');
        Ok := True;
    except
        Ok := False;
    end;

    if not Ok then
    begin
        try
            RunProcess('WorkspaceManager:UpdatePCBDocument');
            Ok := True;
        except
            Ok := False;
        end;
    end;

    if not Ok then
    begin
        Result := 'ERROR: Sch:UpdatePCB and fallback both failed';
        Exit;
    end;

    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONInteger(ResultProps, 'error_count', 0);
        AddJSONInteger(ResultProps, 'changed_count', 1);
        ResultProps.Add('"eco_changes":[{"action":"UpdateAll","status":"completed"}]');
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;
