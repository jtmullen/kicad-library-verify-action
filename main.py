#!/usr/bin/env python3


from kicad_parser import KicadPCB, KicadSCH
from kicad_parser.sexp_parser import *
from actions_toolkit import core
import os
import yaml
import re
import git
import glob
from decimal import *


##to do global lib tables


### Parse Path Replacement Config File into Array
pathReplaceArr = []
def setUpPathReplace(configPath):
    workspacePath = os.environ["GITHUB_WORKSPACE"]
    with open(workspacePath + "/" + configPath) as f:
        pathData = yaml.safe_load(f)

    for key in pathData:
        pathReplaceArr.append(["${{{}}}".format(key), workspacePath + "/" + pathData[key]])

    core.debug("Path Replace Array is: {}".format(pathReplaceArr))


## Replace Paths in the given libPath
## Project path required for KIPRJMOD
def replacePaths(libPath, projectPath):
    libPath = libPath.replace("${KIPRJMOD}", projectPath)
    for pair in pathReplaceArr:
        libPath = libPath.replace(pair[0], pair[1])
    return libPath

## SEXP parser being used adds some artifacts (indices) to the array
## Since they are based on where in the file the fp/symbol is they 
## will not match between files. Remove these artifacts recursively
##  (Should only get to depth of 5 in well formed KiCad file to my knowledge)
def cleanList(dirtyList):
    for item in dirtyList:
        if isinstance(item, list):
            cleanList(item)
    del dirtyList[0]


## KiCad directly edits the embedded Footprints when changed
## This includes things like the reference field, locations, etc.
##   which pretty much always get changed. 
##   Also it adds fields in the pcb for various purposes
## Thus, we only compare fields which shouldn't change. 
## This functions makes a copy of a symbol with only the fields we will compare
def getNeededFootprintFields(modList):
    modListRet = []
    for item in modList:
            ## Only non-list items are "footprint" and the name, which are already validated
            if isinstance(item, list):
                ## Things we ignore
                if(item[0] == "tstamp" 
                    or item[0] == "property"
                    or item[0] == "fp_text"
                    or item[0] == "path"
                    or item[0] == "at"
                    or item[0] == "version"
                    or item[0] == "generator"):
                    continue

                itemCopy = item.copy()

                ## remove timestamps, net, and pintype
                for i in range(len(itemCopy) - 1, -1, -1):
                    smallerItem = itemCopy[i]
                    if isinstance(smallerItem, list):
                        if(smallerItem[0] == "tstamp"
                            or smallerItem[0] == "net"
                            or smallerItem[0] == "pintype"):
                            itemCopy.remove(smallerItem)

                modListRet.append(itemCopy)

    return modListRet


## Return the layer a footprint is on
def getLayer(fp):
    for item in fp:
        if isinstance(item, list):
            if item[0] == "layer":
                return item
   

## Rotating a FP in the PCB edits the pad properties...
## Undo that change here
def unRotateFootprint(fp, rotation):
    core.debug("UnRotating Footprint")
    for item in fp:
        if isinstance(item, list):
            if item[0] == "pad":
                if len(item[4]) == 4:
                    item[4][3] = str(int(item[4][3]) - int(rotation))
                else:
                    item[4].append(str(0 - int(rotation)))

                if int(item[4][3])%360 == 0:
                    del item[4][3]
    return fp


## Moving a FP in the PCB changes the location of any zones. 
## Unfo that movement here
def unMoveZones(fp, fpLocation):
    core.debug("UnMoving Footprint Zones")
    for item in fp:
        if isinstance(item, list):
            if item[0] == "zone":
                for i in range(1, len(item)):
                    if isinstance(item[i], list):
                        if item[i][0] == "polygon":
                            for j in range(1, len(item[i][1])):
                                item[i][1][j][1] = str(float(Decimal(item[i][1][j][1]) - Decimal(fpLocation[1])))
                                item[i][1][j][2] = str(float(Decimal(item[i][1][j][2]) - Decimal(fpLocation[2])))
                                if(float(item[i][1][j][1]).is_integer()):
                                    item[i][1][j][1] = str(int(float(item[i][1][j][1])))
                                if(float(item[i][1][j][2]).is_integer()):
                                    item[i][1][j][2] = str(int(float(item[i][1][j][2])))

    return fp


## If a footprint is moved to a different layer in the PCB
##   all sorts of stuff gets changed
## This function undoes all of that
def unFlipFootprint(fp):

    core.debug("UnFlipping Footprint")
    for item in fp:
        if isinstance(item, list):

            ## Flip Layers
            if item[0] == "layer":
                if "F." in item[1]:
                    item[1] = item[1].replace("F.", "B.")
                else:
                    item[1] = item[1].replace("B.", "F.")
            else:
                for smallerItem in item:
                    if isinstance(smallerItem, list):
                        if smallerItem[0] == "layer" or smallerItem[0] == "layers":
                            for i in range(1, len(smallerItem)):
                                if "F." in smallerItem[i]:
                                    smallerItem[i] = smallerItem[i].replace("F.", "B.")
                                else:
                                    smallerItem[i] = smallerItem[i].replace("B.", "F.")

            ## Transform lines, circles, rectangles, and arcs
            if (item[0] == "fp_line"
                or item[0] == "fp_rect"
                or item[0] == "fp_circle"
                or item[0] == "fp_arc"):

                ## Negate Y in start/end/center/mid
                for i in range(1, len(item)):
                    if isinstance(item[i], list):
                        if (item[i][0] == "start" 
                            or item[i][0] == "end"
                            or item[i][0] == "mid"
                            or item[i][0] == "center"):
                            item[i][2] = str(float(item[i][2]) * -1)
                            if float(item[i][2]).is_integer():
                                item[i][2] = str(int(float(item[i][2])))

                ## additionally swap start/end for arcs
                if item[0] == "fp_arc":
                    endID = 0
                    startID = 0
                    for i in range(1, len(item)):
                        if isinstance(item[i], list):
                            if item[i][0] == "start":
                                startID = i
                            elif item[i][0] == "end":
                                endID = i

                    tempStart = [item[startID][1], item[startID][2]]
                    item[startID][1] = item[endID][1]
                    item[startID][2] = item[endID][2]
                    item[endID][1] = tempStart[0]
                    item[endID][2] = tempStart[1]


            ## Transform Polygon
            elif item[0] == "fp_poly":
                ## Just negate the y
                for i in range(1, len(item)):
                    if isinstance(item[i], list):
                        if item[i][0] == "pts":
                            for j in range (1, len(item[i])):
                                if item[i][j][0] == "xy":
                                    item[i][j][2] = str(float(item[i][j][2]) * -1)
                                    if float(item[i][j][2]).is_integer():
                                        item[i][j][2] = str(int(float(item[i][j][2])))

            ## Transform Zones
            elif item[0] == "zone":
                ## Switch x/y
                for secondItem in item:
                    if isinstance(secondItem, list):
                        for thirdItem in secondItem:
                            if isinstance(thirdItem, list):
                                for fourthItem in thirdItem:
                                    if isinstance(fourthItem, list):
                                        if fourthItem[0] == "xy":
                                            tempX = fourthItem[2]
                                            fourthItem[2] = fourthItem[1]
                                            fourthItem[1] = tempX

    return fp


## Check that all the footprints in a PCB match the library
## Unfortunately the PCB does not keep an unchanged version of footprint
## It makes in-line changes to the location, rotation, layers (flip)
##    and to basic things like the ref des. 
## So we can only check that important things are unchanged
## But we have to do some transformations to get to a state to compare 
def checkPCB(pcbFile, libDict):

    nameOnly = os.path.basename(pcbFile)
    core.start_group("Checking PCB:  {}".format(pcbFile))

    pcbList = []
    with open(pcbFile, 'r') as f:
        pcbList = parseSexp(f.read())
        f.close()

    ##Get all footprints
    fpList = []
    for item in pcbList:
        if isinstance(item, list):
            if item[1] == "footprint":
                fpList.append(item)

    allGood = True
    ## Loop Through all the Footprints
    if fpList:
        cleanList(fpList)
        
        for fp in fpList:
            rawName = fp[1].replace('"','')
            namelist = rawName.split(":", 1)
            libName = namelist[0]
            modName = namelist[1]
            core.info("Checking Footprint: {}...".format(rawName))


            ## Make sure the library is in the lib table
            if libDict.get(libName, None) is None:
                core.error('{}: Library "{}" not found'.format(nameOnly, libName))
                allGood = False
                continue

            ## Get the library file
            libPath = libDict[libName]
            libFile = libPath + "/" + modName + ".kicad_mod"
            modList = []
            try:
                with open(libFile, 'r') as f:
                    modList = parseSexp(f.read())
            except FileNotFoundError:
                core.error("{}: Library File not found at: {}".format(nameOnly, libDict[libName]))
                allGood = False
                continue
            except IOError:
                core.error("{}: Could not open Library File at: {}".format(nameOnly, libDict[libName]))
                allGood = False
                continue

            cleanList(modList)
            libFPList = getNeededFootprintFields(modList)
            pcbFPList = getNeededFootprintFields(fp)
            ## Modify some values (rotaton, layers) to match lib footprint
            fpLocation = []
            for item in fp:
                if isinstance(item, list):
                    if item[0] == "at":
                        fpLocation = item.copy()
                        break

            ## if the fp is rotated un rotate it...
            if(len(fpLocation) == 4 ):
                pcbFPList = unRotateFootprint(pcbFPList, fpLocation[3])

            ## Subtract fp position from zone positions...
            pcbFPList = unMoveZones(pcbFPList, fpLocation)
           
            ## if the fp is flipped to the back, un flip it. 
            pcbLayer = getLayer(pcbFPList)
            libLayer = getLayer(libFPList)

            if libLayer != pcbLayer:
                pcbFPList = unFlipFootprint(pcbFPList)
            
            pcbFPList.sort()
            libFPList.sort()


            if libFPList == pcbFPList:
                core.debug("{} Good".format(modName))
            else:
                core.debug("Lib Footprint:")
                core.debug(libFPList)
                core.debug("PCB Footprint:")
                core.debug(pcbFPList)
                core.error("{}: Footprint {} does not match Library".format(nameOnly, modName))
                allGood = False

    else:
        core.info("No Footprints Found")
        
    core.end_group()

    return allGood 


## Check all the symbols in a given schematic to see if they match the library
## The schematic stores an copy of the symbol in the "lib_symbols" item
## Then modifications instance specific are stored at each "instance". (like refdes)
## Conventiently, this also means we only check each symbol once,
## regardless of how many instances it has. 
def checkSCH(schFile, libDict):

    nameOnly = os.path.basename(schFile)
    core.start_group("Checking Schematic:  {}".format(schFile))

    schList = []
    with open(schFile, 'r') as f:
        schList = parseSexp(f.read())
        f.close()


    ## Get all symbols, conveniently only one copy of each even if multiple instances
    symList = []
    for item in schList:
        if isinstance(item, list):
            if item[1] == "lib_symbols":
                for sym in item:
                    if isinstance(sym, list):
                        symList.append(sym)
                break
    

    allGood = True
    ## Loop through all symbols
    if symList:
        cleanList(symList)
        
        for symbol in symList:
            schSymList = symbol.copy()
            rawName = schSymList[1].replace('"', '')
            nameList = rawName.split(":", 1)
            libName = nameList[0]
            modName = nameList[1]
            
            core.info("Checking Symbol: {}...".format(rawName))

            schSymList[1] = '"{}"'.format(modName)

            ## Make sure library is in this table:
            if libDict.get(libName, None) is None:
                core.error('{}: Library "{}" not found'.format(nameOnly, libName))
                allGood = False
                continue

            ## Get the library file
            try:
                with open(libDict[libName], 'r') as f:
                    libList = parseSexp(f.read())
            except FileNotFoundError:
                core.error("{}: Library File not found at: {}".format(nameOnly, libDict[libName]))
                allGood = False
                continue
            except IOError:
                core.error("{}: Could not open Library File at: {}".format(nameOnly, libDict[libName]))
                allGood = False
                continue

            ## Extract the Symbol From The Library
            symFound = False
            for item in libList:
                if isinstance(item, list):
                    if item[2].replace('"', '') == modName:
                        libSymList = item.copy()
                        symFound = True
                        break

            if not symFound:
                core.error("{}: Symbol {} not found in Library {}".format(nameOnly, modName, libName))
                allGood = False
                continue

            ## Clean List and Check if the match!
            cleanList(libSymList)
            if libSymList == schSymList:
                core.debug("{} Good".format(modName))
            else:
                core.debug("Lib Symbol:")
                core.debug(libSymList)
                core.debug("Sch Symbol:")
                core.debug(schSymList)
                core.error("{}: Symbol {} does not match Library".format(nameOnly, modName))
                allGood = False
    else:
        core.info("No Symbols Found")
        
    core.end_group()

    return allGood
        

## Read the library table and create a dictionary
## Return empty dict if no table
def getLibraryTableAsDict(path, table):

    fileName = path+table
    try:
        with open(fileName, 'r') as f:
            libTable = parseSexp(f.read())
    except FileNotFoundError:
        return {}

    libDict = {}
    for item in libTable:
        if isinstance(item, list):
            libName = item[2][2].replace('"', '')
            libDict[libName] = replacePaths(item[4][2].replace('"', ''), path)

    return libDict


## Checks all the schematics and pcbs in a given directory
## Used to check all in a project if any project file is changed
def checkAllInProjectDir(projectPath):

    ## Get PCBs and SCHs
    core.debug("Looking in directory: {}".format(projectPath))
    schs = glob.glob(projectPath+"*.kicad_sch")
    pcbs = glob.glob(projectPath+"*.kicad_pcb")

    failed = []

    if schs:
        dict = getLibraryTableAsDict(projectPath, "sym-lib-table")
        core.debug("Sch Lib Dict is: {}".format(dict))
        for file in schs:
            if not checkSCH(file, dict):
                failed.append(file)

    if pcbs:
        dict = getLibraryTableAsDict(projectPath, "fp-lib-table")
        core.debug("FP Lib Dict is: {}".format(dict))
        for file in pcbs:
            if not checkPCB(file, dict):
                failed.append(file)

    return failed


## Check all schematics/pcbs recursively from the base directory
## Looks for all kicad pro, sch, pcb or *-lib-table
def checkAllFromBaseDir(baseDir):

    core.debug("Checking all from base directory: {}".format(baseDir))
    allKicadPro = glob.glob(baseDir + "**/*.kicad_pro", recursive = True)
    allKicadPCB = glob.glob(baseDir + "**/*.kicad_pcb", recursive = True)
    allKicadSCH = glob.glob(baseDir + "**/*.kicad_sch", recursive = True)
    allKicadLibFiles = glob.glob(baseDir + "**/*-lib-table", recursive = True)

    dirs = []

    for file in allKicadPro:
        dirs.append(os.path.dirname(file))

    for file in allKicadPCB:
        dirs.append(os.path.dirname(file))

    for file in allKicadSCH:
        dirs.append(os.path.dirname(file))

    for file in allKicadLibFiles:
        dirs.append(os.path.dirname(file))

    ## remove duplicates
    dirs = list(set(dirs))

    core.debug("Directories to Check: {}".format(dirs))

    failed = []
    for directory in dirs:
        failed.extend(checkAllInProjectDir(directory + "/"))

    return failed



##Checks all files in any directory where a kicad file has changed
def checkAllChanged(baseDir):
    
    core.debug("Checking all files in directory with changed file from base dir: {}".format(baseDir))

    with open(os.environ["GITHUB_EVENT_PATH"], 'r') as f:
        eventInfo = json.load(f)
    
    repoName = eventInfo['repository']['full_name']
    ## Figure out what we are running on
    isPR = False
    if "pull_request" in eventInfo:
        prNum = eventInfo['pull_request']['number']
        prBranch = eventInfo['pull_request']['head']['ref']
        prBase = eventInfo['pull_request']['base']['ref']
        prUser = eventInfo['pull_request']['user']['login']
        core.debug("Run for PR#: {} in {} by {}".format(prNum, repoName, prUser))
        core.debug("Branch {} into base {}".format(prBranch, prBase))
        isPR = True
    elif "after" in eventInfo:
        toHash = eventInfo['after']
        fromHash = eventInfo['before']
        branchName = eventInfo['ref']
        core.debug("Run for push on branch: {}".format(branchName))
        core.debug("Hash {} to {}".format(fromHash, toHash))
    else:
        core.set_failed("Error: Config Requires Push or PR Event")

    allChangedFiles = []
    dirs = []

    format = '--name-only'
    repo = git.Git(baseDir)
    if isPR:
        diffed = repo.diff('origin/%s...origin/%s' % (prBase, prBranch), format).split('\n')
    else:
        diffed = diffed = repo.diff('%s...%s' % (fromHash, toHash), format).split('\n')
    
    for line in diffed:
        if len(line):
            allChangedFiles.append(line)
    
    for file in allChangedFiles:
        if(file.endswith(".kicad_pro")
            or file.endswith(".kicad_sch")
            or file.endswith(".kicad_pcb")
            or file.endswith("-lib-table")):
            dirs.append(os.path.dirname(file))
    
    ## remove duplicates
    dirs = list(set(dirs))

    core.debug("Directories to Check: {}".format(dirs))
    
    failed = []
    for directory in dirs:
        failed.extend(checkAllInProjectDir(directory + "/"))

    return failed


def main():
    core.debug("Starting...")
    workspacePath = os.environ["GITHUB_WORKSPACE"]
    baseDir = workspacePath + core.get_input('base_dir', required=False)
    configPath = core.get_input('path_config', required=False)
    checkAll = core.get_boolean_input('check_all', required=False)

    setUpPathReplace(configPath)
    failed = []
    if checkAll:
        failed = checkAllFromBaseDir(baseDir)
    else:
        failed = checkAllChanged(baseDir)

    failed.sort()
    core.set_output("fails", failed)
    core.debug("Failed array: " + str(failed))

    if failed:
        core.set_failed("Failed: Could not verify all symbols/footprints")
    else:
        core.info("All Good!")



main()






##checkAllInProjectDir("test/test_project_modified_symbol/")

##checkPCB("test/test_project_good/test_project_good.kicad_pcb")

##checkSCH("test/test_project_good/test_project_good.kicad_sch")
