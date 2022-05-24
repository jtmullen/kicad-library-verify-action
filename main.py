#!/usr/bin/env python3


from kicad_parser import KicadPCB, KicadSCH
from kicad_parser.sexp_parser import *
import os
import yaml
import re
from decimal import *

##to do global lib tables



def cleanList(dirtyList):
    for item in dirtyList:
        if isinstance(item, list):
            cleanList(item)
    del dirtyList[0]


def replacePaths(libPath, projectPath):
    libPath = libPath.replace("${KIPRJMOD}", projectPath)
    libPath = libPath.replace("${CUSTOM_LIB_PATH}", "/home/jonathan/repos/personal/kicadlibs/")
    return libPath


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
                    smallItem = itemCopy[i]
                    if isinstance(smallerItem, list):
                        if(smallerItem[0] == "tstamp"
                            or smallerItem[0] == "net"
                            or smallerItem[0] == "pintype"):
                            itemCopy.remove(smallerItem)


                modListRet.append(itemCopy)

    return modListRet



def checkPCB(pcbFile, libDict):

    pcbList = []
    with open(pcbFile, 'r') as f:
        pcbList = parseSexp(f.read())
        f.close()

    ##Get all footprints
    fpList = []
    for item in pcbList:
        if isinstance(item, list):
            if item[1] == "footprint":
                fpList.append(cleanList(item))

    ## Get Path of FP Library
    pathParts = pcbFile.split("/")
    fpTableFile = pcbFile.replace(pathParts[-1], "fp-lib-table")


    ## Parse fp lib table
    with open(fpTableFile,'r') as f:
        libTable = parseSexp(f.read())
        f.close()

    libDict = {}
    for item in libTable:
        if isinstance(item, list):
            libName = item[2][2].replace('"', '')
            libDict[libName] = item[4][2].replace('"', '')


    ## Loop Through all the Footprints
    for fp in fpList:
        rawname = fp[1].replace('"','')
        namelist = rawname.split(":", 1)
        libName = namelist[0]
        modName = namelist[1]

        ## Make sure the library is in the lib table
        if libDict.get(libName, None) is None:
            print("Bad table")
            return False

        ## Get the library file
        libPath = replacePaths(libDict[libName], pcbFile.replace(pathParts[-1], ''))
        libFile = libPath + "/" + modName + ".kicad_mod"
        if not os.path.isfile(libFile):
            print("Bad file")
            return False
        print(modName)

        ##Get all the things we want to check from the fp in the file
        pcbFPList = getNeededFootprintFields(fp)
        modList = []
        with open(libFile) as f:
            modList = parseSexp(f.read())
            f.close()

        libFPList = getNeededFootprintFields(cleanList(modList))

        ## Modify some values (rotaton, layers) to match lib footprint
        fpLocation = []
        for item in fp:
            if isinstance(item, list):
                if item[0] == "at":
                    fpLocation = item.copy()
                    break

        if not fpLocation:
            return False

        ## if the fp is rotated un rotate it...
        if(len(fpLocation) == 4 ):
            for item in pcbFPList:
                if isinstance(item, list):
                    if item[0] == "pad":
                        if len(item[4]) == 4:
                            item[4][3] = str(int(item[4][3]) - int(fpLocation[3]))
                        else:
                            item[4].append(str(0 - int(fpLocation[3])))

                        if int(item[4][3])%360 == 0:
                            del item[4][3]

        ## Subtract fp position from zone positions...
        for item in pcbFPList:
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

        ## if the fp is flipped to the back, un flip it. 
        fpLayer = []
        modLayer = []
        for item in pcbFPList:
            if isinstance(item, list):
                if item[0] == "layer":
                    fpLayer = item.copy()
                    break

        for item in libFPList:
            if isinstance(item, list):
                if item[0] == "layer":
                    modLayer = item.copy()
                    break

        if modLayer != fpLayer:
            for item in pcbFPList:
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

                    ## Transform lines, circles, etc
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

                    elif item[0] == "zone":
                        ## Switch x/y
                        print("Zone")
                        print(item)
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

                





        
        pcbFPList.sort()
        libFPList.sort()


        if pcbFPList == libFPList:
            print("Same!")
        else:
            print("\n\n DIFF :(")
            for item in pcbFPList:
                print(item)
            print("\n-----\n")
            for item in libFPList:
                print(item)


       # 



def checkSCH(schFile, libDict):

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
    
    cleanList(symList)
    
    ## parse sym lib table
    pathParts = schFile.split("/")
    symLibTable = schFile.replace(pathParts[-1],"sym-lib-table")

    with open(symLibTable, 'r') as f:
        libTable = parseSexp(f.read())
        f.close()

    libDict = {}
    for item in libTable:
        if isinstance(item, list):
            libName = item[2][2].replace('"', '')
            libDict[libName] = replacePaths(item[4][2].replace('"', ''), schFile.replace(pathParts[-1], ''))

    ## Loop through all symbols
    for symbol in symList:
        schSymList = symbol.copy()
        rawname = schSymList[1].replace('"', '')
        nameList = rawname.split(":", 1)
        libName = nameList[0]
        modName = nameList[1]
        print(modName)
        schSymList[1] = '"' + modName +'"'

        ## Make sure library is in this table:
        if libDict.get(libName, None) is None:
            print("Bad Table")
            return False

        ## Get the library file and extract the symbol
        if not os.path.isfile(libDict[libName]):
            print("Bad File")
            return False

        with open(libDict[libName]) as f:
            libList = parseSexp(f.read())
            f.close()

        #libSymList = []
        for item in libList:
            if isinstance(item, list):
                if item[2].replace('"', '') == modName:
                    libSymList = item.copy()
                    break

        cleanList(libSymList)


        if libSymList == schSymList:
            print("Yes")
        else:
            print(libSymList)
            print("\n\n----\n\n")
            print(schSymList)
        
        



##>>> for item in pcbList:
#...   if isinstance(item, list):
#...     if item[1] == "footprint":
#...       fplist.append(item)
#... 
##>>> print(fplist)



def checkAllInDirectory(path):


##checkPCB("test/test_project_good/test_project_good.kicad_pcb")

checkSCH("test/test_project_good/test_project_good.kicad_sch")
