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

local name = (img and (img["filename"] or img["path"])) or "<nil>"
print(string.format("Placing %s at %s", name, frames_to_timecode(startFrame, fps)))

-- Place a MediaPoolItem on the timeline at a specific record-frame and track.
-- Place a MediaPoolItem on the timeline at a specific record-frame and track.
local function place_at(mediaPool, timeline, clipItem, startFrame, trackIndex, fps)
    local tc = frames_to_timecode(startFrame, fps)
  
    -- Ensure target video track exists
    local have = timeline:GetTrackCount("video") or 0
    while have < trackIndex do
      timeline:AddTrack("video")
      have = timeline:GetTrackCount("video") or have + 1
    end
  
    -- Try direct insert if supported by your Resolve API
    if timeline.InsertClips then
      local ok, res = pcall(function()
        -- Signature is (clipsTable, startTimecode, trackType, trackIndex)
        return timeline:InsertClips({ clipItem }, tc, "video", trackIndex)
      end)
      if ok and res then
        print(string.format("Inserted %s at %s on V%d", (clipItem.GetName and clipItem:GetName() or "<clip>"), tc, trackIndex))
        return true
      end
    end
  
    -- Fallback: append then move the appended item to desired time/track
    local appended = mediaPool:AppendToTimeline({ clipItem })
    print("AppendToTimeline returned:", appended, "target", tc, "V" .. tostring(trackIndex))
    local tlItem = nil
    if type(appended) == "table" and #appended > 0 then
      tlItem = appended[1]
    else
      tlItem = appended -- some builds return the item directly
    end
    if tlItem and tlItem.SetTrackIndex and tlItem.SetStart then
      pcall(function() tlItem:SetTrackIndex("video", trackIndex) end)
      pcall(function() tlItem:SetStart(startFrame) end)
      print(string.format("Appended+Moved %s to %s on V%d", (tlItem.GetName and tlItem:GetName() or "<clip>"), tc, trackIndex))
      return true
    else
      print("Failed to obtain TimelineItem after append; cannot move to target time/track")
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

    -- Ensure V2+ are available
    local baseTrack = 2
    ensure_tracks(timeline, baseTrack + tracks - 1)

    -- Prepare bins
    local rootBin = mediaPool:GetRootFolder()
    local brollBin = get_or_create_bin(mediaPool, rootBin, "B-Roll")
    local entityBins = {}
    for entityName, _ in pairs(entities) do
        entityBins[entityName] = get_or_create_bin(mediaPool, brollBin, entityName)
    end

    -- Import MediaPoolItems and build a quick path->item map
    local pathToItem = {}
    for _, p in ipairs(planned) do
        local entityName = p[2]
        local im = p[3]
        local pth = im and im["path"]
        if pth and pathToItem[pth] == nil then
            local bin = entityBins[entityName]
            mediaPool:SetCurrentFolder(bin)
            local imported = mediaPool:ImportMedia({ pth })
            -- ImportMedia typically returns a table of MediaPoolItem(s)
            if type(imported) == "table" and #imported > 0 then
            pathToItem[pth] = imported[1]
            else
            -- Fallback: locate by file path in the bin
            local clips = (bin.GetClipList and bin:GetClipList()) or {}
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

    -- Placement with simple track occupancy
local durationFrames = math.floor(imgDur * fps + 0.5)
local minGapFrames   = math.floor(minGap * fps + 0.5)

-- seed each V2..V{V2+tracks-1} as free at t = -minGap
local trackEnds = {}
for i = 1, tracks do
  trackEnds[i] = -minGapFrames
end

for _, plan in ipairs(planned) do
  local startFrame  = plan[1]
  local entityName  = plan[2]
  local im          = plan[3]
  local pth         = im and im["path"]
  local item        = pth and pathToItem[pth]

  if not item then
    print("WARN: no MediaPoolItem for path:", tostring(pth))
  else
        local rel = nil
        for i = 1, tracks do
            if startFrame >= (trackEnds[i] + minGapFrames) then
                rel = i; break
            end
        end
        if not rel then
            rel = 1
            startFrame = trackEnds[rel] + minGapFrames
        end
            local absTrack = baseTrack + rel - 1
            local ok = place_at(mediaPool, timeline, item, startFrame, absTrack, fps)
            print(string.format("Placed %s at %s on V%d (ok=%s)",
            (item.GetName and item:GetName() or (im and im["filename"] or "<clip>")),
            frames_to_timecode(startFrame, fps), absTrack, tostring(ok)))
            trackEnds[rel] = startFrame + durationFrames
        end
    end

    print("INFO: Placement complete.")
    win:Hide()
    disp:ExitLoop()
end

win:Show()
disp:RunLoop()
return