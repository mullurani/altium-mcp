// Helper function to convert string to pin electrical type
function StrToPinElectricalType(ElecType: String): TPinElectrical;
begin
    if ElecType = 'eElectricHiZ' then
        Result := eElectricHiZ
    else if ElecType = 'eElectricInput' then
        Result := eElectricInput
    else if ElecType = 'eElectricIO' then
        Result := eElectricIO
    else if ElecType = 'eElectricOpenCollector' then
        Result := eElectricOpenCollector
    else if ElecType = 'eElectricOpenEmitter' then
        Result := eElectricOpenEmitter
    else if ElecType = 'eElectricOutput' then
        Result := eElectricOutput
    else if ElecType = 'eElectricPassive' then
        Result := eElectricPassive
    else if ElecType = 'eElectricPower' then
        Result := eElectricPower
    else
        Result := eElectricPassive; // Default
end;

// Helper function to convert string to pin orientation
function StrToPinOrientation(Orient: String): TRotationBy90;
begin
    if Orient = 'eRotate0' then
        Result := eRotate0
    else if Orient = 'eRotate90' then
        Result := eRotate90
    else if Orient = 'eRotate180' then
        Result := eRotate180
    else if Orient = 'eRotate270' then
        Result := eRotate270
    else
        Result := eRotate0; // Default
end;

// Function to get current schematic library component data
function GetLibrarySymbolReference(ROOT_DIR: String): String;
var
    CurrentLib       : ISch_Lib;
    SchComponent     : ISch_Component;
    PinIterator      : ISch_Iterator;
    Pin              : ISch_Pin;
    ComponentProps   : TStringList;
    PinsArray        : TStringList;
    PinProps         : TStringList;
    OutputLines      : TStringList;
    PinName, PinNum  : String;
    PinType          : String;
    PinOrient        : String;
    PinX, PinY       : Integer;
begin
    Result := '';
    
    // Check if we have a schematic library document
    CurrentLib := SchServer.GetCurrentSchDocument;
    if (CurrentLib.ObjectID <> eSchLib) Then
    begin
        Result := 'ERROR: Please open a schematic library document';
        Exit;
    end;
    
    // Get the currently focused component from the library
    SchComponent := CurrentLib.CurrentSchComponent;
    if SchComponent = Nil Then
    begin
        Result := 'ERROR: No component is currently selected in the library';
        Exit;
    end;
    
    // Create component properties
    ComponentProps := TStringList.Create;
    
    try
        // Add basic component properties
        AddJSONProperty(ComponentProps, 'library_name', ExtractFileName(CurrentLib.DocumentName));
        AddJSONProperty(ComponentProps, 'component_name', SchComponent.LibReference);
        AddJSONProperty(ComponentProps, 'description', SchComponent.ComponentDescription);
        AddJSONProperty(ComponentProps, 'designator', SchComponent.Designator.Text);
        AddJSONInteger(ComponentProps, 'part_count', SchComponent.PartCount);

        // Create an array for pins
        PinsArray := TStringList.Create;
        
        try
            // Create pin iterator
            PinIterator := SchComponent.SchIterator_Create;
            PinIterator.AddFilter_ObjectSet(MkSet(ePin));
            
            Pin := PinIterator.FirstSchObject;
            
            // Process all pins
            while (Pin <> nil) do
            begin
                // Create pin properties
                PinProps := TStringList.Create;
                
                try
                    // Get pin properties
                    PinNum := Pin.Designator;
                    PinName := Pin.Name;
                    
                    // Convert electrical type to string
                    case Pin.Electrical of
                        eElectricHiZ: PinType := 'eElectricHiZ';
                        eElectricInput: PinType := 'eElectricInput';
                        eElectricIO: PinType := 'eElectricIO';
                        eElectricOpenCollector: PinType := 'eElectricOpenCollector';
                        eElectricOpenEmitter: PinType := 'eElectricOpenEmitter';
                        eElectricOutput: PinType := 'eElectricOutput';
                        eElectricPassive: PinType := 'eElectricPassive';
                        eElectricPower: PinType := 'eElectricPower';
                        else PinType := 'eElectricPassive';
                    end;
                    
                    // Convert orientation to string
                    case Pin.Orientation of
                        eRotate0: PinOrient := 'eRotate0';
                        eRotate90: PinOrient := 'eRotate90';
                        eRotate180: PinOrient := 'eRotate180';
                        eRotate270: PinOrient := 'eRotate270';
                        else PinOrient := 'eRotate0';
                    end;
                    
                    // Get coordinates
                    PinX := CoordToMils(Pin.Location.X);
                    PinY := CoordToMils(Pin.Location.Y);
                    
                    // Add pin properties
                    AddJSONProperty(PinProps, 'pin_number', PinNum);
                    AddJSONProperty(PinProps, 'pin_name', PinName);
                    AddJSONProperty(PinProps, 'pin_type', PinType);
                    AddJSONProperty(PinProps, 'pin_orientation', PinOrient);
                    AddJSONNumber(PinProps, 'x', PinX);
                    AddJSONNumber(PinProps, 'y', PinY);
                    AddJSONInteger(PinProps, 'owner_part_id', Pin.OwnerPartId);

                    // Add this pin to the pins array
                    PinsArray.Add(BuildJSONObject(PinProps, 1));
                    
                    // Move to next pin
                    Pin := PinIterator.NextSchObject;
                finally
                    PinProps.Free;
                end;
            end;
            
            SchComponent.SchIterator_Destroy(PinIterator);
            
            // Add pins array to component - pass empty string as the array name
            // because we're adding it directly to the ComponentProps
            ComponentProps.Add('"pins": ' + BuildJSONArray(PinsArray));
            
            // Build final JSON
            OutputLines := TStringList.Create;
            
            try
                OutputLines.Text := BuildJSONObject(ComponentProps);
                Result := WriteJSONToFile(OutputLines, ROOT_DIR+'temp_symbol_reference.json');
            finally
                OutputLines.Free;
            end;
        finally
            PinsArray.Free;
        end;
    finally
        ComponentProps.Free;
    end;
end;

function CreateSchematicSymbol(SymbolName: String; PinsList: TStringList; PartCount: Integer = 1): String;
var
    CurrentLib       : ISch_Lib;
    SchComponent     : ISch_Component;
    SchPin           : ISch_Pin;
    R                : ISch_Rectangle;
    I, J, PinCount   : Integer;
    PinData          : TStringList;
    PinName, PinNum  : String;
    PinType          : String;
    PinOrient        : String;
    PinX, PinY       : Integer;
    PinOwnerPartId   : Integer;
    PinElec          : TPinElectrical;
    PinOrientation   : TRotationBy90;
    MinX, MaxX, MinY, MaxY : Integer;
    HasPins          : Boolean;
    ResultProps      : TStringList;
    Description      : String;
    OutputLines      : TStringList;
begin
    // Check if we have a schematic library document
    CurrentLib := SchServer.GetCurrentSchDocument;
    if (CurrentLib.ObjectID <> eSchLib) Then
    begin
        Result := 'ERROR: Please open a schematic library document';
        Exit;
    end;

    Description := 'New Component';  // Default description

    // Parse the pins list for description and auto-detect PartCount from max owner_part_id
    for I := 0 to PinsList.Count - 1 do
    begin
        if (Pos('Description=', PinsList[I]) = 1) then
        begin
            Description := Copy(PinsList[I], 13, Length(PinsList[I]) - 12);
        end
        else
        begin
            // Check for owner_part_id in pin data to auto-detect PartCount
            PinData := TStringList.Create;
            try
                PinData.Delimiter := '|';
                PinData.DelimitedText := PinsList[I];
                if (PinData.Count >= 7) then
                begin
                    PinOwnerPartId := StrToInt(PinData[6]);
                    if (PinOwnerPartId > PartCount) then
                        PartCount := PinOwnerPartId;
                end;
            finally
                PinData.Free;
            end;
        end;
    end;

    // Create a library component (a page of the library is created)
    SchComponent := SchServer.SchObjectFactory(eSchComponent, eCreate_Default);
    if (SchComponent = Nil) Then
    begin
        Result := 'ERROR: Failed to create component';
        Exit;
    end;

    // Set up parameters for the library component
    SchComponent.CurrentPartID := 1;
    SchComponent.DisplayMode := 0;
    SchComponent.PartCount := PartCount;

    // Define the LibReference and component description
    SchComponent.LibReference := SymbolName;
    SchComponent.ComponentDescription := Description;
    SchComponent.Designator.Text := 'U?';

    // Create a body rectangle for each part
    PinCount := 0;
    for J := 1 to PartCount do
    begin
        // Compute bounding box for this part's pins (including shared pins with OwnerPartId=0)
        MinX := 9999; MaxX := -9999; MinY := 9999; MaxY := -9999;
        HasPins := False;

        for I := 0 to PinsList.Count - 1 do
        begin
            if (Pos('Description=', PinsList[I]) = 1) then Continue;

            PinData := TStringList.Create;
            try
                PinData.Delimiter := '|';
                PinData.DelimitedText := PinsList[I];

                if (PinData.Count >= 6) then
                begin
                    PinX := StrToInt(PinData[4]);
                    PinY := StrToInt(PinData[5]);

                    // Determine owner part id (default 1 for backward compatibility)
                    if (PinData.Count >= 7) then
                        PinOwnerPartId := StrToInt(PinData[6])
                    else
                        PinOwnerPartId := 1;

                    // Include pin in this part's bounding box if it belongs to this part or is shared (0)
                    if (PinOwnerPartId = J) or (PinOwnerPartId = 0) then
                    begin
                        MinX := Min(MinX, PinX);
                        MaxX := Max(MaxX, PinX);
                        MinY := Min(MinY, PinY);
                        MaxY := Max(MaxY, PinY);
                        HasPins := True;
                    end;
                end;
            finally
                PinData.Free;
            end;
        end;

        // Default rectangle if no pins for this part
        if not HasPins then
        begin
            MinX := 300; MinY := 0; MaxX := 1000; MaxY := 1000;
        end;

        // Create a rectangle for this part's body
        R := SchServer.SchObjectFactory(eRectangle, eCreate_Default);
        if (R <> Nil) Then
        begin
            R.LineWidth := eSmall;
            R.Location := Point(MilsToCoord(MinX), MilsToCoord(MinY - 100));
            R.Corner := Point(MilsToCoord(MaxX), MilsToCoord(MaxY + 100));
            R.AreaColor := $00B0FFFF; // Yellow (BGR format)
            R.Color := $00FF0000;     // Blue (BGR format)
            R.IsSolid := True;
            R.OwnerPartId := J;
            R.OwnerPartDisplayMode := 0;
            SchComponent.AddSchObject(R);
        end;

        // Position designator using Part 1's bounding box
        if (J = 1) then
            SchComponent.Designator.Location := Point(MilsToCoord(MinX), MilsToCoord(MaxY + 100));
    end;

    // Add pins to the component
    for I := 0 to PinsList.Count - 1 do
    begin
        if (Pos('Description=', PinsList[I]) = 1) then Continue;

        PinData := TStringList.Create;
        try
            PinData.Delimiter := '|';
            PinData.DelimitedText := PinsList[I];

            if (PinData.Count >= 6) then
            begin
                PinNum := PinData[0];
                PinName := PinData[1];
                PinType := PinData[2];
                PinOrient := PinData[3];
                PinX := StrToInt(PinData[4]);
                PinY := StrToInt(PinData[5]);

                // Determine owner part id (default 1 for backward compatibility)
                if (PinData.Count >= 7) then
                    PinOwnerPartId := StrToInt(PinData[6])
                else
                    PinOwnerPartId := 1;

                // Create a pin
                SchPin := SchServer.SchObjectFactory(ePin, eCreate_Default);
                if (SchPin = Nil) Then
                    Continue;

                // Set pin properties
                PinElec := StrToPinElectricalType(PinType);
                PinOrientation := StrToPinOrientation(PinOrient);

                SchPin.Designator := PinNum;
                SchPin.Name := PinName;
                SchPin.Electrical := PinElec;
                SchPin.Orientation := PinOrientation;
                SchPin.Location := Point(MilsToCoord(PinX), MilsToCoord(PinY));

                // Set ownership to the specified part (0 = shared across all parts)
                SchPin.OwnerPartId := PinOwnerPartId;
                SchPin.OwnerPartDisplayMode := 0;

                SchComponent.AddSchObject(SchPin);
                PinCount := PinCount + 1;
            end;
        finally
            PinData.Free;
        end;
    end;

    // Add the component to the library
    CurrentLib.AddSchComponent(SchComponent);

    // Send a system notification that a new component has been added to the library
    SchServer.RobotManager.SendMessage(nil, c_BroadCast, SCHM_PrimitiveRegistration, SchComponent.I_ObjectAddress);
    CurrentLib.CurrentSchComponent := SchComponent;

    // Refresh library
    CurrentLib.GraphicallyInvalidate;

    // Create result JSON
    ResultProps := TStringList.Create;
    try
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'component_name', SymbolName);
        AddJSONInteger(ResultProps, 'pins_count', PinCount);
        AddJSONInteger(ResultProps, 'part_count', PartCount);

        // Build final JSON
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

// Function to search for a symbol in a schematic library and navigate to it
function SearchLibrarySymbol(ROOT_DIR: String; LibraryPath: String; SymbolName: String): String;
var
    CurrentLib       : ISch_Lib;
    LibIterator      : ISch_Iterator;
    LibComp          : ISch_Component;
    MatchedComp      : ISch_Component;
    ResultProps      : TStringList;
    MatchesArray     : TStringList;
    AllSymbolsArray  : TStringList;
    MatchProps       : TStringList;
    OutputLines      : TStringList;
    SearchUpper      : String;
    LibRefUpper      : String;
    MatchCount       : Integer;
    ServerDoc        : IServerDocument;
    OpenDlg          : TOpenDialog;
    NeedToOpen       : Boolean;
begin
    Result := '';
    MatchedComp := Nil;
    MatchCount := 0;
    SearchUpper := UpperCase(SymbolName);
    NeedToOpen := False;

    // If a library path is provided, open it
    if (LibraryPath <> '') then
    begin
        NeedToOpen := True;
    end
    else
    begin
        // No path provided - check if a SchLib is already open
        if (SchServer <> Nil) then
        begin
            CurrentLib := SchServer.GetCurrentSchDocument;
            if (CurrentLib <> Nil) and (CurrentLib.ObjectID = eSchLib) then
                NeedToOpen := False  // Already have a SchLib open
            else
                NeedToOpen := True;  // No SchLib open, need to browse
        end
        else
            NeedToOpen := True;
    end;

    // If we need to open a library and no path was given, prompt the user
    if NeedToOpen and (LibraryPath = '') then
    begin
        OpenDlg := TOpenDialog.Create(nil);
        try
            OpenDlg.Title := 'Select Schematic Library (.SchLib)';
            OpenDlg.Filter := 'Schematic Library (*.SchLib)|*.SchLib|All Files (*.*)|*.*';
            OpenDlg.FilterIndex := 1;
            if OpenDlg.Execute then
                LibraryPath := OpenDlg.FileName
            else
            begin
                Result := 'ERROR: No library selected. User cancelled the file browser.';
                Exit;
            end;
        finally
            OpenDlg.Free;
        end;
    end;

    // Open the library if we have a path
    if (LibraryPath <> '') then
    begin
        // Check if the file exists
        if not FileExists(LibraryPath) then
        begin
            Result := 'ERROR: Library file not found: ' + LibraryPath;
            Exit;
        end;

        // Open the library document
        ServerDoc := Client.OpenDocument('SchLib', LibraryPath);
        if ServerDoc = Nil then
        begin
            Result := 'ERROR: Failed to open library: ' + LibraryPath;
            Exit;
        end;
        Client.ShowDocument(ServerDoc);
        Sleep(500); // Give Altium time to focus the document
    end;

    // Get the current schematic library document
    CurrentLib := SchServer.GetCurrentSchDocument;
    if CurrentLib = Nil then
    begin
        Result := 'ERROR: No schematic library document is currently open';
        Exit;
    end;

    if (CurrentLib.ObjectID <> eSchLib) then
    begin
        Result := 'ERROR: Current document is not a schematic library. Please open a .SchLib file';
        Exit;
    end;

    // Create arrays for results
    MatchesArray := TStringList.Create;
    AllSymbolsArray := TStringList.Create;
    ResultProps := TStringList.Create;

    try
        // Create library iterator to enumerate all symbols
        // NOTE: Must use SchLibIterator_Create (not SchIterator_Create) for SchLib documents
        LibIterator := CurrentLib.SchLibIterator_Create;
        LibIterator.AddFilter_ObjectSet(MkSet(eSchComponent));

        LibComp := LibIterator.FirstSchObject;
        while (LibComp <> Nil) do
        begin
            LibRefUpper := UpperCase(LibComp.LibReference);

            // Add to all symbols list
            AllSymbolsArray.Add('"' + LibComp.LibReference + '"');

            // Check for partial match
            if (Pos(SearchUpper, LibRefUpper) > 0) then
            begin
                MatchCount := MatchCount + 1;

                // Record this match
                MatchProps := TStringList.Create;
                try
                    AddJSONProperty(MatchProps, 'name', LibComp.LibReference);
                    AddJSONProperty(MatchProps, 'description', LibComp.ComponentDescription);

                    // Check for exact match
                    if (LibRefUpper = SearchUpper) then
                        AddJSONBoolean(MatchProps, 'exact_match', True)
                    else
                        AddJSONBoolean(MatchProps, 'exact_match', False);

                    MatchesArray.Add(BuildJSONObject(MatchProps, 1));
                finally
                    MatchProps.Free;
                end;

                // Prefer exact match, otherwise use first partial match
                if (LibRefUpper = SearchUpper) then
                    MatchedComp := LibComp
                else if (MatchedComp = Nil) then
                    MatchedComp := LibComp;
            end;

            LibComp := LibIterator.NextSchObject;
        end;

        CurrentLib.SchIterator_Destroy(LibIterator);

        // Navigate to the matched component if found
        if (MatchedComp <> Nil) then
        begin
            CurrentLib.CurrentSchComponent := MatchedComp;
            CurrentLib.GraphicallyInvalidate;

            AddJSONBoolean(ResultProps, 'found', True);
            AddJSONProperty(ResultProps, 'navigated_to', MatchedComp.LibReference);
            AddJSONProperty(ResultProps, 'description', MatchedComp.ComponentDescription);
        end
        else
        begin
            AddJSONBoolean(ResultProps, 'found', False);
            AddJSONProperty(ResultProps, 'message', 'No symbol matching "' + SymbolName + '" was found');
        end;

        AddJSONInteger(ResultProps, 'match_count', MatchCount);
        AddJSONProperty(ResultProps, 'library_name', ExtractFileName(CurrentLib.DocumentName));
        AddJSONInteger(ResultProps, 'total_symbols', AllSymbolsArray.Count);
        ResultProps.Add('"matches": ' + BuildJSONArray(MatchesArray));

        // Build final JSON
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR + 'temp_search_symbol.json');
        finally
            OutputLines.Free;
        end;
    finally
        MatchesArray.Free;
        AllSymbolsArray.Free;
        ResultProps.Free;
    end;
end;

// Function to get all schematic component data
function GetSchematicData(ROOT_DIR: String): String;
var
    Project     : IProject;
    Doc         : IDocument;
    CurrentSch  : ISch_Document;
    Iterator    : ISch_Iterator;
    PIterator   : ISch_Iterator;
    Component   : ISch_Component;
    Parameter, NextParameter : ISch_Parameter;
    Rect        : TCoordRect;
    ComponentsArray : TStringList;
    CompProps   : TStringList;
    ParamsProps : TStringList;
    OutputLines : TStringList;
    Designator, Sheet, ParameterName, ParameterValue : String;
    x, y, width, height, rotation : String;
    left, right, top, bottom : String;
    i : Integer;
    SchematicCount, ComponentCount : Integer;
begin
    Result := '';

    // Retrieve the current project
    Project := GetWorkspace.DM_FocusedProject;
    If (Project = Nil) Then
    begin
        ShowMessage('Error: No project is currently open');
        Exit;
    end;

    // Create array for components
    ComponentsArray := TStringList.Create;
    
    try
        // Count the number of schematic documents
        SchematicCount := 0;
        For i := 0 to Project.DM_LogicalDocumentCount - 1 Do
        Begin
            Doc := Project.DM_LogicalDocuments(i);
            If Doc.DM_DocumentKind = 'SCH' Then
                SchematicCount := SchematicCount + 1;
        End;

        // Process each schematic document
        ComponentCount := 0;
        For i := 0 to Project.DM_LogicalDocumentCount - 1 Do
        Begin
            Doc := Project.DM_LogicalDocuments(i);
            If Doc.DM_DocumentKind = 'SCH' Then
            Begin
                // Open the schematic document
                Client.OpenDocument('SCH', Doc.DM_FullPath);
                CurrentSch := SchServer.GetSchDocumentByPath(Doc.DM_FullPath);

                If (CurrentSch <> Nil) Then
                Begin
                    // Get schematic components
                    Iterator := CurrentSch.SchIterator_Create;
                    Iterator.AddFilter_ObjectSet(MkSet(eSchComponent));

                    Component := Iterator.FirstSchObject;
                    While (Component <> Nil) Do
                    Begin
                        // Create component properties
                        CompProps := TStringList.Create;
                        
                        try
                            // Get basic component properties
                            Designator := Component.Designator.Text;
                            Sheet := Doc.DM_FullPath;

                            // Get position, dimensions and rotation
                            x := FloatToStr(CoordToMils(Component.Location.X));
                            y := FloatToStr(CoordToMils(Component.Location.Y));

                            Rect := Component.BoundingRectangle;
                            left := FloatToStr(CoordToMils(Rect.Left));
                            right := FloatToStr(CoordToMils(Rect.Right));
                            top := FloatToStr(CoordToMils(Rect.Top));
                            bottom := FloatToStr(CoordToMils(Rect.Bottom));

                            width := FloatToStr(CoordToMils(Rect.Right - Rect.Left));
                            height := FloatToStr(CoordToMils(Rect.Bottom - Rect.Top));

                            If Component.Orientation = eRotate0 Then
                                rotation := '0'
                            Else If Component.Orientation = eRotate90 Then
                                rotation := '90'
                            Else If Component.Orientation = eRotate180 Then
                                rotation := '180'
                            Else If Component.Orientation = eRotate270 Then
                                rotation := '270'
                            Else
                                rotation := '0';

                            // Add component properties
                            AddJSONProperty(CompProps, 'designator', Designator);
                            AddJSONProperty(CompProps, 'sheet', Sheet);
                            AddJSONNumber(CompProps, 'schematic_x', StrToFloat(x));
                            AddJSONNumber(CompProps, 'schematic_y', StrToFloat(y));
                            AddJSONNumber(CompProps, 'schematic_width', StrToFloat(width));
                            AddJSONNumber(CompProps, 'schematic_height', StrToFloat(height));
                            AddJSONNumber(CompProps, 'schematic_rotation', StrToFloat(rotation));
                            
                            // Get parameters
                            ParamsProps := TStringList.Create;
                            try
                                // Create parameter iterator
                                PIterator := Component.SchIterator_Create;
                                PIterator.AddFilter_ObjectSet(MkSet(eParameter));

                                Parameter := PIterator.FirstSchObject;
                                
                                // Process all parameters
                                while (Parameter <> nil) do
                                begin
                                    // Get this parameter's info
                                    ParameterName := Parameter.Name;
                                    ParameterValue := Parameter.Text;

                                    // Add parameter to the list
                                    AddJSONProperty(ParamsProps, ParameterName, ParameterValue);
                                    
                                    // Move to next parameter
                                    Parameter := PIterator.NextSchObject;
                                end;

                                Component.SchIterator_Destroy(PIterator);
                                
                                // Add parameters to component
                                CompProps.Add('"parameters": ' + BuildJSONObject(ParamsProps, 2));
                                
                                // Add to components array
                                ComponentsArray.Add(BuildJSONObject(CompProps, 1));
                                ComponentCount := ComponentCount + 1;
                            finally
                                ParamsProps.Free;
                            end;
                        finally
                            CompProps.Free;
                        end;

                        // Move to next component
                        Component := Iterator.NextSchObject;
                    End;

                    CurrentSch.SchIterator_Destroy(Iterator);
                End;
            End;
        End;
        
        // Build the final JSON array
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONArray(ComponentsArray);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR+'temp_schematic_data.json');
        finally
            OutputLines.Free;
        end;
    finally
        ComponentsArray.Free;
    end;
end;

// Fallback: component-relative pin transform in TCoord space.
procedure ComputePinSheetMils(Component: ISch_Component; Pin: ISch_Pin;
    PinLengthMils, ExtraOffsetMils: Integer; var WorldX, WorldY: Integer);
var
    LenCoord, OffCoord, HotX, HotY : TCoord;
begin
    if PinLengthMils < 0 then
        LenCoord := Pin.PinLength
    else
        LenCoord := MilsToCoord(PinLengthMils);
    if ExtraOffsetMils > 0 then
        OffCoord := MilsToCoord(ExtraOffsetMils)
    else
        OffCoord := 0;

    HotX := Pin.Location.X;
    HotY := Pin.Location.Y;
    case Pin.Orientation of
        eRotate0:   HotX := HotX + LenCoord + OffCoord;
        eRotate90:  HotY := HotY + LenCoord + OffCoord;
        eRotate180: HotX := HotX - LenCoord - OffCoord;
        eRotate270: HotY := HotY - LenCoord - OffCoord;
    end;
    if Component.IsMirrored then
        HotX := -HotX;

    case Component.Orientation of
        eRotate90:
        begin
            WorldX := CoordToMils(Component.Location.X - HotY);
            WorldY := CoordToMils(Component.Location.Y + HotX);
        end;
        eRotate180:
        begin
            WorldX := CoordToMils(Component.Location.X - HotX);
            WorldY := CoordToMils(Component.Location.Y - HotY);
        end;
        eRotate270:
        begin
            WorldX := CoordToMils(Component.Location.X + HotY);
            WorldY := CoordToMils(Component.Location.Y - HotX);
        end;
    else
        begin
            WorldX := CoordToMils(Component.Location.X + HotX);
            WorldY := CoordToMils(Component.Location.Y + HotY);
        end;
    end;
end;

// Resolve pin electrical hot-spot in sheet mils (document-level pin location).
function GetPinHotSpotMils(SchDoc: ISch_Document; Component: ISch_Component;
    Pin: ISch_Pin; ExtraOffsetMils: Integer; var WorldX, WorldY: Integer): Boolean;
var
    Rect           : TCoordRect;
    SpatialIt      : ISch_Iterator;
    Obj            : ISch_BasicContainer;
    DocPin         : ISch_Pin;
    LenCoord, OffCoord : TCoord;
    HotX, HotY     : TCoord;
begin
    Result := False;
    if (SchDoc = Nil) or (Component = Nil) or (Pin = Nil) then Exit;

    Rect := Component.BoundingRectangle;
    SpatialIt := SchDoc.SchIterator_Create;
    if SpatialIt = Nil then Exit;
    try
        SpatialIt.AddFilter_ObjectSet(MkSet(ePin));
        SpatialIt.AddFilter_Area(Rect.Left, Rect.Bottom, Rect.Right, Rect.Top);
        DocPin := SpatialIt.FirstSchObject;
        while DocPin <> Nil do
        begin
            if (DocPin.OwnerSchComponent <> Nil) and
               (DocPin.OwnerSchComponent.Designator.Text = Component.Designator.Text) and
               ((DocPin.Designator = Pin.Designator) or (DocPin.Name = Pin.Name)) then
            begin
                if ExtraOffsetMils > 0 then
                    OffCoord := MilsToCoord(ExtraOffsetMils)
                else
                    OffCoord := 0;
                LenCoord := DocPin.PinLength;
                HotX := DocPin.Location.X;
                HotY := DocPin.Location.Y;
                case DocPin.Orientation of
                    eRotate0:   HotX := HotX + LenCoord + OffCoord;
                    eRotate90:  HotY := HotY + LenCoord + OffCoord;
                    eRotate180: HotX := HotX - LenCoord - OffCoord;
                    eRotate270: HotY := HotY - LenCoord - OffCoord;
                end;
                WorldX := CoordToMils(HotX);
                WorldY := CoordToMils(HotY);
                Result := True;
                Exit;
            end;
            DocPin := SpatialIt.NextSchObject;
        end;
    finally
        SchDoc.SchIterator_Destroy(SpatialIt);
    end;

    // Fallback: component-relative transform in TCoord space
    ComputePinSheetMils(Component, Pin, -1, ExtraOffsetMils, WorldX, WorldY);
    Result := True;
end;

procedure RegisterSchObject(SchDoc: ISch_Document; SchObject: ISch_BasicContainer);
begin
    SchDoc.RegisterSchObjectInContainer(SchObject);
    SchServer.RobotManager.SendMessage(SchDoc.I_ObjectAddress, c_BroadCast,
        SCHM_PrimitiveRegistration, SchObject.I_ObjectAddress);
end;

procedure AddSchWireSegment(SchDoc: ISch_Document; X1Mils, Y1Mils, X2Mils, Y2Mils: Integer);
var
    Wire : ISch_Wire;
begin
    Wire := SchServer.SchObjectFactory(eWire, eCreate_Default);
    if Wire = Nil then Exit;
    Wire.VerticesCount := 2;
    Wire.Vertex[1] := Point(MilsToCoord(X1Mils), MilsToCoord(Y1Mils));
    Wire.Vertex[2] := Point(MilsToCoord(X2Mils), MilsToCoord(Y2Mils));
    RegisterSchObject(SchDoc, Wire);
end;

procedure AddSchWireOrthogonal(SchDoc: ISch_Document; X1Mils, Y1Mils, X2Mils, Y2Mils: Integer);
begin
    if (X1Mils = X2Mils) or (Y1Mils = Y2Mils) then
        AddSchWireSegment(SchDoc, X1Mils, Y1Mils, X2Mils, Y2Mils)
    else
    begin
        AddSchWireSegment(SchDoc, X1Mils, Y1Mils, X1Mils, Y2Mils);
        AddSchWireSegment(SchDoc, X1Mils, Y2Mils, X2Mils, Y2Mils);
    end;
end;

function FindComponentPin(SchDoc: ISch_Document; const Designator, PinId: String;
    var Component: ISch_Component; var Pin: ISch_Pin): Boolean;
var
    Iterator    : ISch_Iterator;
    PinIterator : ISch_Iterator;
begin
    Result := False;
    Component := Nil;
    Pin := Nil;
    if SchDoc = Nil then Exit;

    Iterator := SchDoc.SchIterator_Create;
    Iterator.AddFilter_ObjectSet(MkSet(eSchComponent));
    Component := Iterator.FirstSchObject;
    while Component <> Nil do
    begin
        if Component.Designator.Text = Designator then
        begin
            PinIterator := Component.SchIterator_Create;
            PinIterator.AddFilter_ObjectSet(MkSet(ePin));
            Pin := PinIterator.FirstSchObject;
            while Pin <> Nil do
            begin
                if (Pin.Designator = PinId) or (Pin.Name = PinId) then
                begin
                    Component.SchIterator_Destroy(PinIterator);
                    SchDoc.SchIterator_Destroy(Iterator);
                    Result := True;
                    Exit;
                end;
                Pin := PinIterator.NextSchObject;
            end;
            Component.SchIterator_Destroy(PinIterator);
        end;
        Component := Iterator.NextSchObject;
    end;
    SchDoc.SchIterator_Destroy(Iterator);
end;

// --------------------------------------------------------------------------
// Idempotency helpers: let apply/connect be safely re-run without duplicating.
// --------------------------------------------------------------------------

// Returns the state of an existing net-label / power-port near a pin:
//   0 = nothing there (caller should place a new one)
//   1 = a label/port with the SAME net is already present (skip)
//   2 = a label/port with a DIFFERENT net occupies this spot (conflict)
function PinConnectionState(SchDoc: ISch_Document; HotX, HotY, OffX, OffY: Integer;
    NetName: String): Integer;
var
    Iterator : ISch_Iterator;
    Obj      : ISch_GraphicalObject;
    Lbl      : ISch_NetLabel;
    Pwr      : ISch_PowerObject;
    Txt      : String;
    ObjX, ObjY, Tol : Integer;
    Matches  : Boolean;
begin
    Result := 0;
    Tol := 200;
    Iterator := SchDoc.SchIterator_Create;
    Iterator.AddFilter_ObjectSet(MkSet(eNetLabel, ePowerObject));
    Obj := Iterator.FirstSchObject;
    while Obj <> Nil do
    begin
        Txt  := '';
        ObjX := -1000000;
        ObjY := -1000000;
        if Obj.ObjectId = eNetLabel then
        begin
            Lbl  := Obj;
            Txt  := Lbl.Text;
            ObjX := CoordToMils(Lbl.Location.X);
            ObjY := CoordToMils(Lbl.Location.Y);
        end
        else if Obj.ObjectId = ePowerObject then
        begin
            Pwr  := Obj;
            Txt  := Pwr.Text;
            ObjX := CoordToMils(Pwr.Location.X);
            ObjY := CoordToMils(Pwr.Location.Y);
        end;

        Matches := ((Abs(ObjX - OffX) <= Tol) and (Abs(ObjY - OffY) <= Tol)) or
                   ((Abs(ObjX - HotX) <= Tol) and (Abs(ObjY - HotY) <= Tol));
        if Matches then
        begin
            if UpperCase(Trim(Txt)) = UpperCase(Trim(NetName)) then
                Result := 1
            else
                Result := 2;
            Break;
        end;
        Obj := Iterator.NextSchObject;
    end;
    SchDoc.SchIterator_Destroy(Iterator);
end;

// True if a single wire already has vertices near both (X1,Y1) and (X2,Y2).
function WireSegmentExists(SchDoc: ISch_Document; X1, Y1, X2, Y2: Integer): Boolean;
var
    Iterator   : ISch_Iterator;
    Wire       : ISch_Wire;
    i, vx, vy, Tol : Integer;
    Has1, Has2 : Boolean;
begin
    Result := False;
    Tol := 50;
    Iterator := SchDoc.SchIterator_Create;
    Iterator.AddFilter_ObjectSet(MkSet(eWire));
    Wire := Iterator.FirstSchObject;
    while Wire <> Nil do
    begin
        Has1 := False;
        Has2 := False;
        for i := 1 to Wire.VerticesCount do
        begin
            vx := CoordToMils(Wire.Vertex[i].X);
            vy := CoordToMils(Wire.Vertex[i].Y);
            if (Abs(vx - X1) <= Tol) and (Abs(vy - Y1) <= Tol) then Has1 := True;
            if (Abs(vx - X2) <= Tol) and (Abs(vy - Y2) <= Tol) then Has2 := True;
        end;
        if Has1 and Has2 then
        begin
            Result := True;
            Break;
        end;
        Wire := Iterator.NextSchObject;
    end;
    SchDoc.SchIterator_Destroy(Iterator);
end;

// True if the orthogonal (L-shaped or straight) wire path already exists.
function OrthogonalWireExists(SchDoc: ISch_Document; X1, Y1, X2, Y2: Integer): Boolean;
begin
    if (X1 = X2) or (Y1 = Y2) then
        Result := WireSegmentExists(SchDoc, X1, Y1, X2, Y2)
    else
        Result := WireSegmentExists(SchDoc, X1, Y1, X1, Y2) and
                  WireSegmentExists(SchDoc, X1, Y2, X2, Y2);
end;

function ConnectPins(AssignmentsList: TStringList): String;
var
    Project       : IProject;
    ProjectIdx, AssignIdx, DocIdx : Integer;
    Doc           : IDocument;
    SchDoc        : ISch_Document;
    ComponentA, ComponentB : ISch_Component;
    PinA, PinB    : ISch_Pin;
    AssignData    : TStringList;
    DesA, DesB, PinAId, PinBId : String;
    X1, Y1, X2, Y2 : Integer;
    ConnectedCount, SkippedCount, SkippedExisting : Integer;
    ConnectedFlags: TStringList;
    ResultProps   : TStringList;
    NotFoundArray : TStringList;
    PlacedDetails : TStringList;
    TargetDoc     : IDocument;
    Found         : Boolean;
begin
    ConnectedCount := 0;
    SkippedCount := 0;
    SkippedExisting := 0;
    AssignData := TStringList.Create;
    ConnectedFlags := TStringList.Create;
    ResultProps := TStringList.Create;
    NotFoundArray := TStringList.Create;
    PlacedDetails := TStringList.Create;
    TargetDoc := Nil;
    try
        AssignData.Delimiter := '|';
        for AssignIdx := 0 to AssignmentsList.Count - 1 do
            ConnectedFlags.Add('0');

        for AssignIdx := 0 to AssignmentsList.Count - 1 do
        begin
            AssignData.DelimitedText := AssignmentsList[AssignIdx];
            if AssignData.Count = 3 then
            begin
                DesA := Trim(AssignData[0]);
                DesB := DesA;
                PinAId := Trim(AssignData[1]);
                PinBId := Trim(AssignData[2]);
            end
            else if AssignData.Count >= 4 then
            begin
                DesA := Trim(AssignData[0]);
                PinAId := Trim(AssignData[1]);
                DesB := Trim(AssignData[2]);
                PinBId := Trim(AssignData[3]);
            end
            else
            begin
                SkippedCount := SkippedCount + 1;
                NotFoundArray.Add('"' + JSONEscapeString(AssignmentsList[AssignIdx]) + '"');
                Continue;
            end;

            Found := False;
            for ProjectIdx := 0 to GetWorkspace.DM_ProjectCount - 1 do
            begin
                Project := GetWorkspace.DM_Projects(ProjectIdx);
                if Project = Nil then Continue;

                for DocIdx := 0 to Project.DM_LogicalDocumentCount - 1 do
                begin
                    Doc := Project.DM_LogicalDocuments(DocIdx);
                    if Doc.DM_DocumentKind <> 'SCH' then Continue;

                    Client.OpenDocument('SCH', Doc.DM_FullPath);
                    SchDoc := SchServer.GetSchDocumentByPath(Doc.DM_FullPath);
                    if SchDoc = Nil then Continue;

                    if not FindComponentPin(SchDoc, DesA, PinAId, ComponentA, PinA) then Continue;
                    if not FindComponentPin(SchDoc, DesB, PinBId, ComponentB, PinB) then Continue;

                    GetPinHotSpotMils(SchDoc, ComponentA, PinA, 0, X1, Y1);
                    GetPinHotSpotMils(SchDoc, ComponentB, PinB, 0, X2, Y2);

                    if OrthogonalWireExists(SchDoc, X1, Y1, X2, Y2) then
                    begin
                        // Already wired -- treat as done so re-runs are idempotent.
                        ConnectedFlags[AssignIdx] := '1';
                        SkippedExisting := SkippedExisting + 1;
                        TargetDoc := Doc;
                        Found := True;
                        Break;
                    end;

                    SchServer.ProcessControl.PreProcess(SchDoc, '');
                    AddSchWireOrthogonal(SchDoc, X1, Y1, X2, Y2);
                    SchServer.ProcessControl.PostProcess(SchDoc, '');
                    SchDoc.GraphicallyInvalidate;

                    ConnectedFlags[AssignIdx] := '1';
                    ConnectedCount := ConnectedCount + 1;
                    TargetDoc := Doc;
                    Found := True;
                    PlacedDetails.Add('"' + JSONEscapeString(DesA + '.' + PinAId + ' to ' +
                        DesB + '.' + PinBId + ' on ' + Doc.DM_FullPath) + '"');
                    Break;
                end;
                if Found then Break;
            end;

            if ConnectedFlags[AssignIdx] <> '1' then
            begin
                SkippedCount := SkippedCount + 1;
                NotFoundArray.Add('"' + JSONEscapeString(DesA + '.' + PinAId + ' to ' +
                    DesB + '.' + PinBId) + '"');
            end;
        end;

        if TargetDoc <> Nil then
        begin
            TargetDoc.DM_OpenAndFocusDocument;
            Sleep(300);
        end;

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONInteger(ResultProps, 'connected_count', ConnectedCount);
        AddJSONInteger(ResultProps, 'skipped_existing', SkippedExisting);
        AddJSONInteger(ResultProps, 'skipped_count', SkippedCount);
        if PlacedDetails.Count > 0 then
            ResultProps.Add('"connected": ' + BuildJSONArray(PlacedDetails));
        if NotFoundArray.Count > 0 then
            ResultProps.Add('"not_found": ' + BuildJSONArray(NotFoundArray));
        Result := BuildJSONObject(ResultProps);
    finally
        AssignData.Free;
        ConnectedFlags.Free;
        ResultProps.Free;
        NotFoundArray.Free;
        PlacedDetails.Free;
    end;
end;

function PlacePinConnections(AssignmentsList: TStringList; UsePowerPort: Boolean): String;
var
    Project       : IProject;
    ProjectIdx, I, J : Integer;
    Doc           : IDocument;
    SchDoc        : ISch_Document;
    Iterator      : ISch_Iterator;
    PinIterator   : ISch_Iterator;
    Component     : ISch_Component;
    Pin           : ISch_Pin;
    NetLabel      : ISch_NetLabel;
    PowerPort     : ISch_PowerObject;
    AssignData    : TStringList;
    Designator, PinName, NetName : String;
    HotX, HotY, PortX, PortY : Integer;
    PlacedCount, SkippedCount, SkippedExisting, ConflictCount, ConnState : Integer;
    PlacedFlags   : TStringList;
    ResultProps   : TStringList;
    NotFoundArray : TStringList;
    PlacedDetails : TStringList;
    ConflictArray : TStringList;
    LabelOffsetMils : Integer;
    TargetDoc     : IDocument;
begin
    PlacedCount := 0;
    SkippedCount := 0;
    SkippedExisting := 0;
    ConflictCount := 0;
    LabelOffsetMils := 200;
    PlacedFlags := TStringList.Create;
    for I := 0 to AssignmentsList.Count - 1 do
        PlacedFlags.Add('0');
    AssignData    := TStringList.Create;
    ResultProps   := TStringList.Create;
    NotFoundArray := TStringList.Create;
    PlacedDetails := TStringList.Create;
    ConflictArray := TStringList.Create;
    try
        AssignData.Delimiter := '|';
        TargetDoc := Nil;

        for ProjectIdx := 0 to GetWorkspace.DM_ProjectCount - 1 do
        begin
            Project := GetWorkspace.DM_Projects(ProjectIdx);
            if Project = Nil then Continue;

            for I := 0 to Project.DM_LogicalDocumentCount - 1 do
            begin
                Doc := Project.DM_LogicalDocuments(I);
                if Doc.DM_DocumentKind <> 'SCH' then Continue;

                Client.OpenDocument('SCH', Doc.DM_FullPath);
                SchDoc := SchServer.GetSchDocumentByPath(Doc.DM_FullPath);
                if SchDoc = Nil then Continue;

                SchServer.ProcessControl.PreProcess(SchDoc, '');
                Iterator := SchDoc.SchIterator_Create;
                Iterator.AddFilter_ObjectSet(MkSet(eSchComponent));
                Component := Iterator.FirstSchObject;
                while Component <> Nil do
                begin
                    for J := 0 to AssignmentsList.Count - 1 do
                    begin
                        if PlacedFlags[J] = '1' then Continue;
                        AssignData.DelimitedText := AssignmentsList[J];
                        if AssignData.Count < 3 then Continue;
                        Designator := Trim(AssignData[0]);
                        if Component.Designator.Text <> Designator then Continue;

                        PinName := Trim(AssignData[1]);
                        NetName := Trim(AssignData[2]);

                        PinIterator := Component.SchIterator_Create;
                        PinIterator.AddFilter_ObjectSet(MkSet(ePin));
                        Pin := PinIterator.FirstSchObject;
                        while Pin <> Nil do
                        begin
                            if (Pin.Name = PinName) or (Pin.Designator = PinName) then
                            begin
                                GetPinHotSpotMils(SchDoc, Component, Pin, 0, HotX, HotY);
                                GetPinHotSpotMils(SchDoc, Component, Pin, LabelOffsetMils, PortX, PortY);

                                // Idempotency: skip if this pin already carries this
                                // net; flag a conflict if a different net is here.
                                ConnState := PinConnectionState(SchDoc, HotX, HotY, PortX, PortY, NetName);
                                if ConnState = 1 then
                                begin
                                    PlacedFlags[J] := '1';
                                    SkippedExisting := SkippedExisting + 1;
                                    TargetDoc := Doc;
                                    Break;
                                end
                                else if ConnState = 2 then
                                begin
                                    PlacedFlags[J] := '1';
                                    ConflictCount := ConflictCount + 1;
                                    ConflictArray.Add('"' + JSONEscapeString(Designator + '.' + PinName +
                                        ' wants ' + NetName + ' but another net is already placed here') + '"');
                                    Break;
                                end;

                                if UsePowerPort then
                                begin
                                    AddSchWireSegment(SchDoc, HotX, HotY, PortX, PortY);
                                    PowerPort := SchServer.SchObjectFactory(ePowerObject, eCreate_Default);
                                    if PowerPort <> Nil then
                                    begin
                                        PowerPort.Location := Point(MilsToCoord(PortX), MilsToCoord(PortY));
                                        PowerPort.Text := NetName;
                                        if (UpperCase(NetName) = 'GND')  or (UpperCase(NetName) = 'VSS')  or
                                           (UpperCase(NetName) = 'AGND') or (UpperCase(NetName) = 'PGND') then
                                        begin
                                            PowerPort.Style := ePowerGndPower;
                                            PowerPort.Orientation := eRotate270;
                                        end
                                        else
                                        begin
                                            PowerPort.Style := ePowerBar;
                                            PowerPort.Orientation := eRotate90;
                                        end;
                                        RegisterSchObject(SchDoc, PowerPort);
                                        PlacedFlags[J] := '1';
                                        PlacedCount := PlacedCount + 1;
                                        TargetDoc := Doc;
                                        PlacedDetails.Add('"' + JSONEscapeString(Designator + '.' + PinName) +
                                            ' on ' + JSONEscapeString(Doc.DM_FullPath) +
                                            ' at ' + IntToStr(PortX) + ',' + IntToStr(PortY) + ' mils"');
                                    end;
                                end
                                else
                                begin
                                    AddSchWireSegment(SchDoc, HotX, HotY, PortX, PortY);
                                    NetLabel := SchServer.SchObjectFactory(eNetLabel, eCreate_Default);
                                    if NetLabel <> Nil then
                                    begin
                                        NetLabel.Location := Point(MilsToCoord(PortX), MilsToCoord(PortY));
                                        NetLabel.Text := NetName;
                                        NetLabel.Orientation := eRotate0;
                                        RegisterSchObject(SchDoc, NetLabel);
                                        PlacedFlags[J] := '1';
                                        PlacedCount := PlacedCount + 1;
                                        TargetDoc := Doc;
                                        PlacedDetails.Add('"' + JSONEscapeString(Designator + '.' + PinName) +
                                            ' on ' + JSONEscapeString(Doc.DM_FullPath) +
                                            ' at ' + IntToStr(PortX) + ',' + IntToStr(PortY) + ' mils"');
                                    end;
                                end;
                                Break;
                            end;
                            Pin := PinIterator.NextSchObject;
                        end;
                        Component.SchIterator_Destroy(PinIterator);
                    end;
                    Component := Iterator.NextSchObject;
                end;
                SchDoc.SchIterator_Destroy(Iterator);
                SchServer.ProcessControl.PostProcess(SchDoc, '');
                SchDoc.GraphicallyInvalidate;
            end;
        end;

        if TargetDoc <> Nil then
        begin
            TargetDoc.DM_OpenAndFocusDocument;
            Sleep(300);
        end;

        for I := 0 to AssignmentsList.Count - 1 do
        begin
            if PlacedFlags[I] <> '1' then
            begin
                AssignData.DelimitedText := AssignmentsList[I];
                if AssignData.Count >= 2 then
                    NotFoundArray.Add('"' + JSONEscapeString(Trim(AssignData[0]) + '.' + Trim(AssignData[1])) + '"')
                else
                    NotFoundArray.Add('"' + JSONEscapeString(AssignmentsList[I]) + '"');
                SkippedCount := SkippedCount + 1;
            end;
        end;

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONInteger(ResultProps, 'placed_count', PlacedCount);
        AddJSONInteger(ResultProps, 'skipped_existing', SkippedExisting);
        AddJSONInteger(ResultProps, 'conflict_count', ConflictCount);
        AddJSONInteger(ResultProps, 'skipped_count', SkippedCount);
        if PlacedDetails.Count > 0 then
            ResultProps.Add('"placed": ' + BuildJSONArray(PlacedDetails));
        if ConflictArray.Count > 0 then
            ResultProps.Add('"conflicts": ' + BuildJSONArray(ConflictArray));
        if NotFoundArray.Count > 0 then
            ResultProps.Add('"not_found": ' + BuildJSONArray(NotFoundArray));
        Result := BuildJSONObject(ResultProps);
    finally
        AssignData.Free;
        PlacedFlags.Free;
        ResultProps.Free;
        NotFoundArray.Free;
        PlacedDetails.Free;
        ConflictArray.Free;
    end;
end;

function PlaceNetLabels(AssignmentsList: TStringList): String;
begin
    Result := PlacePinConnections(AssignmentsList, False);
end;

function PlacePowerPorts(AssignmentsList: TStringList): String;
begin
    Result := PlacePinConnections(AssignmentsList, True);
end;

// Place a differential-pair directive (a Parameter Set carrying a DIFFPAIR
// parameter) touching the positive net of each pair. The _P/_N net labels must
// already be placed (Altium pairs by that naming convention). Assignments are
// the POSITIVE pins: "DESIGNATOR|PIN|NET_P". The Parameter Set creation is
// wrapped in try/except so a runtime failure never affects the labels; the only
// hard dependency is the eParameterSet object-id constant.
function PlaceDiffPairDirectives(AssignmentsList: TStringList): String;
var
    Project       : IProject;
    ProjectIdx, AssignIdx, DocIdx : Integer;
    Doc           : IDocument;
    SchDoc        : ISch_Document;
    Component     : ISch_Component;
    Pin           : ISch_Pin;
    AssignData    : TStringList;
    Des, PinId, NetName : String;
    HotX, HotY, OffX, OffY : Integer;
    ParamSet      : ISch_GraphicalObject;
    Param         : ISch_Parameter;
    PlacedCount, SkippedCount : Integer;
    ResultProps, NotFoundArray : TStringList;
    TargetDoc     : IDocument;
    Found, DirectiveOK : Boolean;
begin
    PlacedCount := 0;
    SkippedCount := 0;
    AssignData := TStringList.Create;
    ResultProps := TStringList.Create;
    NotFoundArray := TStringList.Create;
    TargetDoc := Nil;
    try
        AssignData.Delimiter := '|';
        for AssignIdx := 0 to AssignmentsList.Count - 1 do
        begin
            AssignData.DelimitedText := AssignmentsList[AssignIdx];
            if AssignData.Count < 3 then
            begin
                SkippedCount := SkippedCount + 1;
                Continue;
            end;
            Des     := Trim(AssignData[0]);
            PinId   := Trim(AssignData[1]);
            NetName := Trim(AssignData[2]);

            Found := False;
            for ProjectIdx := 0 to GetWorkspace.DM_ProjectCount - 1 do
            begin
                Project := GetWorkspace.DM_Projects(ProjectIdx);
                if Project = Nil then Continue;
                for DocIdx := 0 to Project.DM_LogicalDocumentCount - 1 do
                begin
                    Doc := Project.DM_LogicalDocuments(DocIdx);
                    if Doc.DM_DocumentKind <> 'SCH' then Continue;
                    Client.OpenDocument('SCH', Doc.DM_FullPath);
                    SchDoc := SchServer.GetSchDocumentByPath(Doc.DM_FullPath);
                    if SchDoc = Nil then Continue;
                    if not FindComponentPin(SchDoc, Des, PinId, Component, Pin) then Continue;

                    // Sit the directive on the wire just off the pin so it
                    // "touches" the net (Altium attaches it by proximity).
                    GetPinHotSpotMils(SchDoc, Component, Pin, 100, OffX, OffY);

                    DirectiveOK := False;
                    SchServer.ProcessControl.PreProcess(SchDoc, '');
                    try
                        ParamSet := SchServer.SchObjectFactory(eParameterSet, eCreate_Default);
                        if ParamSet <> Nil then
                        begin
                            ParamSet.Location := Point(MilsToCoord(OffX), MilsToCoord(OffY));
                            // A parameter set is recognised as a directive by the
                            // presence of a specifically-named parameter.
                            Param := SchServer.SchObjectFactory(eParameter, eCreate_Default);
                            if Param <> Nil then
                            begin
                                Param.Name := 'DIFFPAIR';
                                Param.Text := 'True';
                                Param.Location := Point(MilsToCoord(OffX), MilsToCoord(OffY));
                                ParamSet.AddSchObject(Param);
                            end;
                            RegisterSchObject(SchDoc, ParamSet);
                            DirectiveOK := True;
                        end;
                    except
                        DirectiveOK := False;
                    end;
                    SchServer.ProcessControl.PostProcess(SchDoc, '');
                    SchDoc.GraphicallyInvalidate;

                    if DirectiveOK then
                    begin
                        PlacedCount := PlacedCount + 1;
                        TargetDoc := Doc;
                    end
                    else
                        NotFoundArray.Add('"' + JSONEscapeString(Des + '.' + PinId +
                            ' (' + NetName + ') directive failed') + '"');
                    Found := True;
                    Break;
                end;
                if Found then Break;
            end;

            if not Found then
            begin
                SkippedCount := SkippedCount + 1;
                NotFoundArray.Add('"' + JSONEscapeString(Des + '.' + PinId) + '"');
            end;
        end;

        if TargetDoc <> Nil then
        begin
            TargetDoc.DM_OpenAndFocusDocument;
            Sleep(200);
        end;

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONInteger(ResultProps, 'directives_placed', PlacedCount);
        AddJSONInteger(ResultProps, 'skipped_count', SkippedCount);
        if NotFoundArray.Count > 0 then
            ResultProps.Add('"not_found": ' + BuildJSONArray(NotFoundArray));
        Result := BuildJSONObject(ResultProps);
    finally
        AssignData.Free;
        ResultProps.Free;
        NotFoundArray.Free;
    end;
end;

function GetUnconnectedPins: String;
var
    Project       : IProject;
    Doc           : IDocument;
    SchDoc        : ISch_Document;
    Net           : INet;
    NetPin        : INetItem;
    Iterator      : ISch_Iterator;
    PinIterator   : ISch_Iterator;
    Component     : ISch_Component;
    Pin           : ISch_Pin;
    ConnectedKeys : TStringList;
    ResultArray   : TStringList;
    PinProps      : TStringList;
    Key, Designator, PinName, PinNum : String;
    I, J, K       : Integer;
begin
    Project := GetWorkspace.DM_FocusedProject;
    if Project = Nil then
    begin
        Result := 'ERROR: No project is currently open. Open a project (.PrjPcb) to use this tool.';
        Exit;
    end;

    SchDoc := SchServer.GetCurrentSchDocument;
    if (SchDoc = Nil) or (SchDoc.ObjectID = eSchLib) then
    begin
        Result := 'ERROR: Please open and focus a schematic document (.SchDoc)';
        Exit;
    end;

    Project.DM_Compile;

    ConnectedKeys := TStringList.Create;
    ResultArray   := TStringList.Create;
    try
        ConnectedKeys.Sorted := False;
        ConnectedKeys.Duplicates := dupIgnore;

        for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        begin
            Doc := Project.DM_LogicalDocuments(I);
            if Doc.DM_DocumentKind <> 'SCH' then Continue;
            if Doc.DM_FullPath <> SchDoc.DocumentName then Continue;

            for J := 0 to Doc.DM_NetCount - 1 do
            begin
                Net := Doc.DM_Nets(J);
                for K := 0 to Net.DM_PinCount - 1 do
                begin
                    NetPin := Net.DM_Pins(K);
                    Key := NetPin.DM_PhysicalPartDesignator + '|' + NetPin.DM_PinNumber;
                    ConnectedKeys.Add(Key);
                end;
            end;
        end;

        Iterator := SchDoc.SchIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eSchComponent));
        Component := Iterator.FirstSchObject;
        while Component <> Nil do
        begin
            Designator := Component.Designator.Text;
            PinIterator := Component.SchIterator_Create;
            PinIterator.AddFilter_ObjectSet(MkSet(ePin));
            Pin := PinIterator.FirstSchObject;
            while Pin <> Nil do
            begin
                PinName := Pin.Name;
                PinNum  := Pin.Designator;
                Key := Designator + '|' + PinNum;
                if ConnectedKeys.IndexOf(Key) < 0 then
                begin
                    PinProps := TStringList.Create;
                    try
                        AddJSONProperty(PinProps, 'designator', Designator);
                        AddJSONProperty(PinProps, 'pin_name', PinName);
                        AddJSONProperty(PinProps, 'pin_number', PinNum);
                        ResultArray.Add(BuildJSONObject(PinProps, 1));
                    finally
                        PinProps.Free;
                    end;
                end;
                Pin := PinIterator.NextSchObject;
            end;
            Component.SchIterator_Destroy(PinIterator);
            Component := Iterator.NextSchObject;
        end;
        SchDoc.SchIterator_Destroy(Iterator);

        Result := BuildJSONArray(ResultArray);
    finally
        ConnectedKeys.Free;
        ResultArray.Free;
    end;
end;

// Read back the ACTUAL connectivity of every schematic pin in the focused
// project. Used by check_netlist (diff vs intent) and export_netlist.
// Returns a JSON array of {designator, pin_name, pin_number, sheet, net},
// where net = "" for an unconnected pin. Requires an open project (.PrjPcb)
// because it calls DM_Compile to resolve nets.
function GetPinNets: String;
var
    Project       : IProject;
    Doc           : IDocument;
    SchDoc        : ISch_Document;
    Net           : INet;
    NetPin        : INetItem;
    Iterator      : ISch_Iterator;
    PinIterator   : ISch_Iterator;
    Component     : ISch_Component;
    Pin           : ISch_Pin;
    NetMap        : TStringList;
    ResultArray   : TStringList;
    PinProps      : TStringList;
    Key, Designator, PinName, PinNum, NetName, Sheet : String;
    I, J, K, MapIdx : Integer;
begin
    Project := GetWorkspace.DM_FocusedProject;
    if Project = Nil then
    begin
        Result := 'ERROR: No project is currently open. Open a project (.PrjPcb) to use this tool.';
        Exit;
    end;

    Project.DM_Compile;

    NetMap      := TStringList.Create;
    ResultArray := TStringList.Create;
    try
        NetMap.NameValueSeparator := '=';

        // Build a pin -> net map from the compiled nets across all SCH docs.
        for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        begin
            Doc := Project.DM_LogicalDocuments(I);
            if Doc.DM_DocumentKind <> 'SCH' then Continue;

            for J := 0 to Doc.DM_NetCount - 1 do
            begin
                Net := Doc.DM_Nets(J);
                NetName := Net.DM_NetName;
                for K := 0 to Net.DM_PinCount - 1 do
                begin
                    NetPin := Net.DM_Pins(K);
                    Key := NetPin.DM_PhysicalPartDesignator + '|' + NetPin.DM_PinNumber;
                    if NetMap.IndexOfName(Key) < 0 then
                        NetMap.Add(Key + '=' + NetName);
                end;
            end;
        end;

        // Emit every pin with its resolved net (or "" if unconnected).
        for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        begin
            Doc := Project.DM_LogicalDocuments(I);
            if Doc.DM_DocumentKind <> 'SCH' then Continue;

            Client.OpenDocument('SCH', Doc.DM_FullPath);
            SchDoc := SchServer.GetSchDocumentByPath(Doc.DM_FullPath);
            if SchDoc = Nil then Continue;
            Sheet := Doc.DM_FullPath;

            Iterator := SchDoc.SchIterator_Create;
            Iterator.AddFilter_ObjectSet(MkSet(eSchComponent));
            Component := Iterator.FirstSchObject;
            while Component <> Nil do
            begin
                Designator := Component.Designator.Text;
                PinIterator := Component.SchIterator_Create;
                PinIterator.AddFilter_ObjectSet(MkSet(ePin));
                Pin := PinIterator.FirstSchObject;
                while Pin <> Nil do
                begin
                    PinName := Pin.Name;
                    PinNum  := Pin.Designator;
                    Key := Designator + '|' + PinNum;
                    MapIdx := NetMap.IndexOfName(Key);
                    if MapIdx >= 0 then
                        NetName := NetMap.ValueFromIndex[MapIdx]
                    else
                        NetName := '';

                    PinProps := TStringList.Create;
                    try
                        AddJSONProperty(PinProps, 'designator', Designator);
                        AddJSONProperty(PinProps, 'pin_name', PinName);
                        AddJSONProperty(PinProps, 'pin_number', PinNum);
                        AddJSONProperty(PinProps, 'sheet', Sheet);
                        AddJSONProperty(PinProps, 'net', NetName);
                        ResultArray.Add(BuildJSONObject(PinProps, 1));
                    finally
                        PinProps.Free;
                    end;
                    Pin := PinIterator.NextSchObject;
                end;
                Component.SchIterator_Destroy(PinIterator);
                Component := Iterator.NextSchObject;
            end;
            SchDoc.SchIterator_Destroy(Iterator);
        end;

        Result := BuildJSONArray(ResultArray);
    finally
        NetMap.Free;
        ResultArray.Free;
    end;
end;
