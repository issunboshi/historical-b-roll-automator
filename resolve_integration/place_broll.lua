-- place_broll.lua
-- Pure-Lua Resolve script: read entities_map.json, prompt options, place clips on V2+.
-- Install to: ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/

-- Minimal embedded JSON decoder (sufficient for entities_map.json)
-- Supports: objects, arrays, strings (with escapes), numbers, true/false/null
local function json_decode(str)
    local pos = 1
    local len = #str
    local function peek() return str:sub(pos, pos) end
    local function nextc() local c = str:sub(pos, pos); pos = pos + 1; return c end
    local function skip_ws()
        while true do
            local c = peek()
            if c == ' ' or c == '\t' or c == '\r' or c == '\n' then
                pos = pos + 1
            else
                break
            end
        end
    end
    local function parse_string()
        local quote = nextc() -- should be "
        local buf = {}
        while true do
            local c = nextc()
            if c == "" then return nil, "Unterminated string" end
            if c == '"' then break end
            if c == "\\" then
                local e = nextc()
                if e == '"' or e == '\\' or e == '/' then
                    table.insert(buf, e)
                elseif e == 'b' then table.insert(buf, '\b')
                elseif e == 'f' then table.insert(buf, '\f')
                elseif e == 'n' then table.insert(buf, '\n')
                elseif e == 'r' then table.insert(buf, '\r')
                elseif e == 't' then table.insert(buf, '\t')
                elseif e == 'u' then
                    local hex = str:sub(pos, pos+3)
                    if not hex:match('^%x%x%x%x$') then return nil, "Invalid \\u escape" end
                    pos = pos + 4
                    local code = tonumber(hex, 16)
                    -- Basic unicode to UTF-8
                    if code < 0x80 then
                        table.insert(buf, string.char(code))
                    elseif code < 0x800 then
                        table.insert(buf, string.char(0xC0 + math.floor(code/0x40)))
                        table.insert(buf, string.char(0x80 + (code % 0x40)))
                    else
                        table.insert(buf, string.char(0xE0 + math.floor(code/0x1000)))
                        table.insert(buf, string.char(0x80 + (math.floor(code/0x40) % 0x40)))
                        table.insert(buf, string.char(0x80 + (code % 0x40)))
                    end
                else
                    return nil, "Invalid escape"
                end
            else
                table.insert(buf, c)
            end
        end
        return table.concat(buf)
    end
    local function parse_number()
        local s = pos
        local c = peek()
        if c == '-' then pos = pos + 1 end
        while peek():match('%d') do pos = pos + 1 end
        if peek() == '.' then
            pos = pos + 1
            while peek():match('%d') do pos = pos + 1 end
        end
        local ch = peek()
        if ch == 'e' or ch == 'E' then
            pos = pos + 1
            local sgn = peek()
            if sgn == '+' or sgn == '-' then pos = pos + 1 end
            while peek():match('%d') do pos = pos + 1 end
        end
        local num = str:sub(s, pos-1)
        local val = tonumber(num)
        if val == nil then return nil, "Invalid number" end
        return val
    end
    local parse_value
    local function parse_array()
        local arr = {}
        nextc() -- [
        skip_ws()
        if peek() == ']' then nextc(); return arr end
        while true do
            local v, err = parse_value()
            if err then return nil, err end
            table.insert(arr, v)
            skip_ws()
            local c = nextc()
            if c == ']' then break
            elseif c ~= ',' then return nil, "Expected , or ] in array" end
            skip_ws()
        end
        return arr
    end
    local function parse_object()
        local obj = {}
        nextc() -- {
        skip_ws()
        if peek() == '}' then nextc(); return obj end
        while true do
            if peek() ~= '"' then return nil, "Expected string key" end
            local key, err = parse_string()
            if err then return nil, err end
            skip_ws()
            if nextc() ~= ':' then return nil, "Expected :" end
            skip_ws()
            local val; val, err = parse_value()
            if err then return nil, err end
            obj[key] = val
            skip_ws()
            local c = nextc()
            if c == '}' then break
            elseif c ~= ',' then return nil, "Expected , or } in object" end
            skip_ws()
        end
        return obj
    end
    function parse_value()
        skip_ws()
        local c = peek()
        if c == '"' then
            return parse_string()
        elseif c == '{' then
            return parse_object()
        elseif c == '[' then
            return parse_array()
        elseif c == 't' and str:sub(pos, pos+3) == "true" then pos = pos + 4; return true
        elseif c == 'f' and str:sub(pos, pos+4) == "false" then pos = pos + 5; return false
        elseif c == 'n' and str:sub(pos, pos+3) == "null" then pos = pos + 4; return nil
        else
            return parse_number()
        end
    end
    local v, err = parse_value()
    if err then return nil, err end
    skip_ws()
    return v
end

-- Replace the entire frames_to_timecode function with this:
-- local function frames_to_timecode(frames, fps)
--     if not fps or fps <= 0 then
--         fps = 25
--     end
--     if frames == nil then
--         return "00:00:00:00"
--     end
--     local f = math.floor(frames)
--     local fr = f % math.floor(fps)
--     local secs = math.floor(f / math.floor(fps))
--     local hh = math.floor(secs / 3600)
--     local mm = math.floor((secs % 3600) / 60)
--     local ss = secs % 60
--     return string.format("%02d:%02d:%02d:%02d", hh, mm, ss, fr)
-- end

-- Convert record-frame index to "HH:MM:SS:FF"
local function frames_to_timecode(frames, fps)
    if not fps or fps <= 0 then fps = 25 end
    if frames == nil then return "00:00:00:00" end
    local f = math.floor(frames)
    local fr = f % math.floor(fps)
    local secs = math.floor(f / math.floor(fps))
    local hh = math.floor(secs / 3600)
    local mm = math.floor((secs % 3600) / 60)
    local ss = secs % 60
    return string.format("%02d:%02d:%02d:%02d", hh, mm, ss, fr)
  end
local function srt_tc_to_frames(tc, fps)
    -- "HH:MM:SS,mmm"
    local hh, mm, ss, ms = tc:match("(%d%d):(%d%d):(%d%d),(%d%d%d)")
    if not hh then return 0 end
    local total = tonumber(hh) * 3600 + tonumber(mm) * 60 + tonumber(ss) + (tonumber(ms) or 0) / 1000
    return math.floor(total * fps + 0.5)
end

local function ensure_tracks(timeline, min_required_index)
    local current = timeline:GetTrackCount("video")
    while current < min_required_index do
        timeline:AddTrack("video")
        current = timeline:GetTrackCount("video")
    end
end

-- Get items in a specific video track (supports multiple Resolve API variants)
local function get_items_in_video_track(timeline, trackIndex)
    local items = {}
    if timeline.GetItemsInTrack then
        local t = timeline:GetItemsInTrack("video", trackIndex) or {}
        for _, it in pairs(t) do
            table.insert(items, it)
        end
    elseif timeline.GetItemListInTrack then
        local t = timeline:GetItemListInTrack("video", trackIndex) or {}
        for _, it in ipairs(t) do
            table.insert(items, it)
        end
    end
    return items
end

-- Get items across all video tracks
local function get_all_video_items(timeline)
    local all = {}
    local vcount = timeline:GetTrackCount("video") or 0
    for i = 1, vcount do
        local t
        if timeline.GetItemsInTrack then
            t = timeline:GetItemsInTrack("video", i) or {}
            for _, it in pairs(t) do table.insert(all, it) end
        elseif timeline.GetItemListInTrack then
            t = timeline:GetItemListInTrack("video", i) or {}
            for _, it in ipairs(t) do table.insert(all, it) end
        end
    end
    return all
end

local bmd = bmd or require("BlackmagicRawAPI") or {} -- bmd provided in Resolve
local fusion_ok, fusion = pcall(function() return bmd.scriptapp("Fusion") end)
if not fusion_ok or not fusion then
    print("Fusion UI not available. Run from Resolve Workspace -> Scripts.")
    return
end
local resolve_ok, resolve = pcall(function() return bmd.scriptapp("Resolve") end)
resolve:OpenPage("edit")
if not resolve_ok or not resolve then
    fusion.UIManager:ShowMessageBox("Could not connect to Resolve.", {Title="Error", Buttons={"OK"}})
    return
end

local ui = bmd.UIManager or (fusion and fusion.UIManager)
if not ui then
    print("UI Manager not available (bmd.UIManager is nil).")
    return
end
local disp = bmd.UIDispatcher(ui)

local width = 560
local win = disp:AddWindow(
    {
        ID = "BrollPlacerLua",
        WindowTitle = "B-Roll Placer (Lua)",
        Geometry = {100, 100, width, 220},
    },
    ui:VGroup{
        ID = "root",
        Spacing = 6,

        ui:HGroup{
            Spacing = 6,
            ui:Label{ Text = "entities_map.json:" },
            ui:LineEdit{ ID = "MapPath", PlaceholderText = "Select entities_map.json", Weight = 1 },
            ui:Button{ ID = "Browse", Text = "Browse..." },
        },

        ui:HGroup{
            ui:Label{ Text = "Tracks:" },
            ui:SpinBox{ ID = "Tracks", Minimum = 2, Maximum = 32, Value = 4 },
            ui:Label{ Text = "Image duration (s):" },
            ui:SpinBox{ ID = "ImgDur", Decimals = 1, SingleStep = 0.5, Minimum = 0.5, Maximum = 60.0, Value = 4.0 },
            ui:Label{ Text = "Min gap (s):" },
            ui:SpinBox{ ID = "MinGap", Decimals = 1, SingleStep = 0.5, Minimum = 0.0, Maximum = 30.0, Value = 2.0 },
        },

        ui:CheckBox{ ID = "AllowNonPD", Text = "Allow non-public-domain (write credits file)", Checked = false },

        ui:HGroup{
            Alignment = { AlignHCenter = true },
            ui:Button{ ID = "Run", Text = "Run" },
            ui:Button{ ID = "Cancel", Text = "Cancel" },
        },
    }
)

function win.On.Browse.Clicked(ev)
    local path = fusion:RequestFile({Type="File", Save=false, Title="Select entities_map.json", Filter="JSON files (*.json)"})
    if path and #path > 0 then
        win:Find("MapPath").Text = path
    end
end

function win.On.Cancel.Clicked(ev)
    win:Hide()
    disp:ExitLoop()
end

local function read_json(path)
    local f = io.open(path, "r")
    if not f then return nil, "Cannot open file" end
    local content = f:read("*a")
    f:close()
    local obj, err = json_decode(content)
    if err then return nil, "JSON parse error: " .. tostring(err) end
    return obj, nil
end

local function get_or_create_bin(mediaPool, parent, name)
    local subs = parent:GetSubFolderList() or {}
    for _, sub in ipairs(subs) do
        if sub:GetName() == name then
            return sub
        end
    end
    return mediaPool:AddSubFolder(parent, name)
end

 
-- Place a MediaPoolItem on the timeline at a specific record-frame and track.
-- Place a MediaPoolItem on the timeline at a specific record-frame and track.
local function place_at(mediaPool, timeline, clipItem, startFrame, trackIndex, fps)
    local tc = frames_to_timecode(startFrame, fps)
    -- Ensure target video track exists
    local have = (timeline.GetTrackCount and timeline:GetTrackCount("video")) or 0
    while have < trackIndex do
        if timeline.AddTrack then
            timeline:AddTrack("video")
        else
            pcall(function() timeline:AddTrack("video") end)
        end
        have = (timeline.GetTrackCount and timeline:GetTrackCount("video")) or (have + 1)
    end
    -- Try direct insert (DR 18+): InsertClips(clipsTable, trackType, trackIndex, recordFrame)
    if timeline.InsertClips then
        local ok, res = pcall(function()
            return timeline:InsertClips({ clipItem }, "video", trackIndex, startFrame)
        end)
        if ok and res then
            print(string.format("Inserted %s at %s on V%d", (clipItem.GetName and clipItem:GetName() or "<clip>"), tc, trackIndex))
            return true
        end
    end
    -- Fallback: append then move to desired time/track
    local appended = mediaPool:AppendToTimeline({ clipItem })
    local tlItem = (type(appended) == "table" and appended[1]) or appended
    if tlItem and tlItem.SetTrackIndex and tlItem.SetStart then
        pcall(function() tlItem:SetTrackIndex("video", trackIndex) end)
        pcall(function() tlItem:SetStart(startFrame) end)
        print(string.format("Appended+Moved %s -> %s on V%d", (tlItem.GetName and tlItem:GetName() or "<clip>"), tc, trackIndex))
        return true
    else
        print("WARN: append did not return a TimelineItem; cannot reposition")
        return false
    end
end

function win.On.Run.Clicked(ev)
    local mp = win:Find("MapPath").Text or ""
    if mp == "" then
        print("ERROR: Please select entities_map.json.")
        return
    end
    local tracks = tonumber(win:Find("Tracks").Value) or 4
    if tracks < 2 then tracks = 2 end
    local imgDur = tonumber(win:Find("ImgDur").Value) or 4.0
    local minGap = tonumber(win:Find("MinGap").Value) or 2.0
    local allowNonPD = win:Find("AllowNonPD").Checked and true or false

    print(string.format("UI Settings - imgDur: %.1f, minGap: %.1f, tracks: %d, allowNonPD: %s",
        imgDur, minGap, tracks, tostring(allowNonPD)))

    local projectManager = resolve:GetProjectManager()
    local project = projectManager:GetCurrentProject()
    if not project then
        print("ERROR: No active Resolve project.")
        return
    end
    local mediaPool = project:GetMediaPool()
    local timeline = project:GetCurrentTimeline()
    if not timeline then
        print("ERROR: No active timeline.")
        return
    end
    local fps = tonumber(project:GetSetting("timelineFrameRate")) or 25.0
    -- Ensure Edit page is active and prepare V2
    pcall(function() resolve:OpenPage("edit") end)
    pcall(function() timeline:SetTrackLock("video", 1, true) end)
    pcall(function() timeline:SetTrackLock("video", 2, false) end)

    local data, jerr = read_json(mp)
    if not data then
        print("ERROR: err or 'Failed to read JSON'.")
        return
    end
    local entities = data["entities"]
    if not entities then
        print("ERROR: No 'entities' in map.")
        return
    end

    -- Build planned (startFrame, entityName, imageEntry)
    local planned = {}
    for entityName, payload in pairs(entities) do
        local images = payload["images"]
        local occs = payload["occurrences"]
        if images and occs and #images > 0 and #occs > 0 then
            -- filter by PD
            local filtered = {}
            for _, img in ipairs(images) do
                if img["category"] == "public_domain" or allowNonPD then
                    table.insert(filtered, img)
                end
            end
            if #filtered > 0 then
                local rr = 1
                for _, occ in ipairs(occs) do
                    local tc = occ["timecode"]
                    if tc then
                        local img = filtered[((rr - 1) % #filtered) + 1]
                        rr = rr + 1
                        local fr = srt_tc_to_frames(tc, fps)
                        table.insert(planned, {fr, entityName, img})
                    end
                end
            end
        end
    end
    table.sort(planned, function(a,b) return a[1] < b[1] end)
    if #planned == 0 then
        print("ERROR: No placements to make.")
        return
    end
    -- Get timeline bounds for validation
    local timelineStart = 0
    local timelineEnd = (timeline.GetEndFrame and timeline:GetEndFrame()) or 0
    print(string.format("Timeline bounds: %d to %d frames (%.1f to %.1f seconds)",
        timelineStart, timelineEnd, timelineStart/fps, timelineEnd/fps))

    -- Ensure V2+ are available
    local baseTrack = 2
    ensure_tracks(timeline, baseTrack + tracks - 1)

    -- Prepare bins
    local rootBin = mediaPool:GetRootFolder()
    local brollBin = get_or_create_bin(mediaPool, rootBin, "B-Roll")

    -- Import MediaPoolItems and build a quick path->item map
    local pathToItem = {}
    for _, p in ipairs(planned) do
        local im = p[3]
        local pth = im and im["path"]
        if pth and pathToItem[pth] == nil then
            mediaPool:SetCurrentFolder(brollBin)
            local imported = mediaPool:ImportMedia({ pth })
            -- ImportMedia typically returns a table of MediaPoolItem(s); capture first
            if type(imported) == "table" and #imported > 0 then
                pathToItem[pth] = imported[1]
            else
                -- Fallback: locate by file path in the B-Roll bin
                if brollBin and brollBin.GetClipList then
                    local clips = brollBin:GetClipList() or {}
                    for _, it in ipairs(clips) do
                        local props = it.GetClipProperty and it:GetClipProperty() or {}
                        if props and props["File Path"] == pth then
                            pathToItem[pth] = it
                            break
                        end
                    end
                end
            end
        end
    end

    -- Derive clip duration and minimum gap in frames
    local durationFrames = math.floor(imgDur * fps + 0.5)
    local minGapFrames   = math.floor(minGap * fps + 0.5)
    print(string.format("Calculated - durationFrames: %d (%.1fs), minGapFrames: %d (%.1fs) at %.1f fps",
        durationFrames, imgDur, minGapFrames, minGap, fps))

    -- Build placement plan - place clips at their original timestamps
    local placements = {}
    for _, plan in ipairs(planned) do
        local startFrame = plan[1]
        local im = plan[3]
        local pth = im and im["path"]
        local item = pth and pathToItem[pth]
        if not item then
            print("WARN: no MediaPoolItem for path:", tostring(pth))
        elseif startFrame >= timelineStart and startFrame + durationFrames <= timelineEnd then
            -- Place at original timestamp if it fits within timeline bounds
            table.insert(placements, { target = startFrame, item = item, path = pth, im = im })
        else
            print(string.format("SKIP: timestamp %s would place clip outside timeline bounds",
                frames_to_timecode(startFrame, fps)))
        end
    end
    -- Place in ascending order and enforce non-overlap with min gap
    table.sort(placements, function(a, b) return a.target < b.target end)
    local lastEnd = timelineEnd  -- Start appending from current timeline end

    for _, pl in ipairs(placements) do
        -- This clip will be appended to the timeline end with proper spacing

        local item = pl.item
        local clipName = (pl.im and pl.im["filename"] or pl.path or "<clip>")
        local placedOK = false

        -- Append all clips to the end of timeline with enforced gaps
        -- Get current timeline end and calculate position with minimum gap
        local currentEnd = (timeline.GetEndFrame and timeline:GetEndFrame()) or 0
        local appendPosition = math.max(currentEnd, lastEnd + minGapFrames)

        -- Make sure we don't extend beyond a reasonable timeline extension
        -- Allow extending timeline by up to 10 minutes for clips
        local maxTimelineEnd = timelineEnd + (10 * 60 * fps)  -- 10 minutes
        if appendPosition + durationFrames <= maxTimelineEnd then
            -- Try to place at the calculated append position using InsertClips
            if timeline and timeline.InsertClips then
                local ok, ret = pcall(function()
                    return timeline:InsertClips({ item }, "video", 2, appendPosition)
                end)
                if ok and ret and type(ret) == "table" and #ret > 0 then
                    print(string.format("Placed %s at %s on V2 (enforced spacing)",
                        tostring(clipName),
                        frames_to_timecode(appendPosition, fps)))
                    placedOK = true
                    lastEnd = appendPosition + durationFrames
                else
                    print(string.format("InsertClips failed for %s, trying append", tostring(clipName)))
                end
            end

            if not placedOK then
                -- Fallback: use AppendToTimeline and check if it worked
                print(string.format("Trying AppendToTimeline for %s", tostring(clipName)))
                local preItemCount = #get_all_video_items(timeline)
                local appendResult = mediaPool:AppendToTimeline({ item })
                print(string.format("AppendToTimeline returned: %s", tostring(appendResult)))

                -- Check if items were actually added
                local postItemCount = #get_all_video_items(timeline)
                print(string.format("Timeline items: %d -> %d", preItemCount, postItemCount))

                if postItemCount > preItemCount then
                    print(string.format("Successfully added %s to timeline", tostring(clipName)))
                    lastEnd = lastEnd + durationFrames  -- Advance for proper spacing calculation
                else
                    print(string.format("Failed to add %s to timeline", tostring(clipName)))
                end
            end
        else
            print(string.format("SKIP: %s would extend timeline too far (position %s)",
                tostring(clipName), frames_to_timecode(appendPosition, fps)))
        end
    end

    print(string.format("INFO: Placement complete. Processed %d clips.", #placements))
    win:Hide()
    disp:ExitLoop()
end

win:Show()
disp:RunLoop()
return