#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2015-2016, Joe Keenan, joe@flyingdiver.com

import re
import time
import logging

from Queue import Queue

from SMTPServer import SMTPServer
from IMAPServer import IMAPServer
from POPServer import POPServer

from ghpu import GitHubPluginUpdater

kCurDevVersCount = 3  # current version of plugin devices


################################################################################
class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))

    def startup(self):
        self.logger.info(u"Starting Better Email")

        self.updater = GitHubPluginUpdater(self)
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', 24)) * 60.0 * 60.0
        self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
        self.next_update_check = time.time()

        self.serverDict = dict()
        self.triggers = {}

    def shutdown(self):
        self.logger.info(u"Shutting down Better Email")

    ####################

    def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
        self.logger.debug("getDeviceConfigUiValues, typeID = " + typeId)
        valuesDict = indigo.Dict(pluginProps)
        errorsDict = indigo.Dict()

        if len(valuesDict) == 0:
            self.logger.debug("getDeviceConfigUiValues: no values, populating encryptionType and hostPort")
            if typeId == "imapAccount":
                valuesDict["encryptionType"] = "SSL"
                valuesDict["hostPort"] = "993"
            elif typeId == "popAccount":
                valuesDict["encryptionType"] = "SSL"
                valuesDict["hostPort"] = "995"
            elif typeId == "smtpAccount":
                valuesDict["encryptionType"] = "SSL"
                valuesDict["hostPort"] = "465"
        else:
            self.logger.debug("getDeviceConfigUiValues: no change, already populated")

        return (valuesDict, errorsDict)

    def listEncryptionTypes(self, filter=u'', valuesDict=None, typeId=u'', targetId=0):
        encryptionTypes = []
        if filter == "imapAccount":
            encryptionTypes = [("SSL", "SSL"), ("None", "None")]
        elif filter == "popAccount":
            encryptionTypes = [("SSL", "SSL"), ("None", "None")]
        elif filter == "smtpAccount":
            encryptionTypes = [("SSL", "SSL"), ("StartTLS", "StartTLS"), ("None", "None")]
        return encryptionTypes

    def encryptionSelected(self, valuesDict=None, filter=u'', typeId=u'', targetId=0):
        encryptionType = valuesDict.get(u'encryptionType', u'')
        if filter == "imapAccount":
            if encryptionType == "None":
                valuesDict['hostPort'] = 143
            elif encryptionType == "SSL":
                valuesDict['hostPort'] = 993
        elif filter == "popAccount":
            if encryptionType == "None":
                valuesDict['hostPort'] = 110
            elif encryptionType == "SSL":
                valuesDict['hostPort'] = 995
        elif filter == "smtpAccount":
            if encryptionType == "None":
                valuesDict['hostPort'] = 587
            elif encryptionType == "SSL":
                valuesDict['hostPort'] = 465
            elif encryptionType == "StartTLS":
                valuesDict['hostPort'] = 587
        return valuesDict

    ####################

    def triggerStartProcessing(self, trigger):
        self.logger.debug("Adding Trigger %s (%d)" % (trigger.name, trigger.id))
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug("Removing Trigger %s (%d)" % (trigger.name, trigger.id))
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    def triggerCheck(self, device):
        self.logger.debug("Checking Triggers for Device %s (%d)" % (device.name, device.id))

        for triggerId, trigger in sorted(self.triggers.iteritems()):
            self.logger.debug("\tChecking Trigger %s (%d), %s" % (trigger.name, trigger.id, trigger.pluginTypeId))

            if trigger.pluginProps["serverID"] != str(device.id):
                self.logger.debug("\t\tSkipping Trigger %s (%s), wrong device: %s" % (trigger.name, trigger.id, device.id))
            else:
                if trigger.pluginTypeId == "regexMatch":
                    field = trigger.pluginProps["fieldPopUp"]
                    pattern = trigger.pluginProps["regexPattern"]
                    self.logger.debug("\tChecking Device State %s for Pattern: %s" % (field, pattern))
                    cPattern = re.compile(pattern)
                    match = cPattern.search(device.states[field])
                    if match:
                        regexMatch = match.group()
                        self.logger.debug("\tExecuting Trigger %s (%d), match: %s" % (trigger.name, trigger.id, regexMatch))
                        device.updateStateOnServer(key="regexMatch", value=regexMatch)
                        indigo.trigger.execute(trigger)
                    else:
                        self.logger.debug("\tNo Match for Trigger %s (%d)" % (trigger.name, trigger.id))
                elif trigger.pluginTypeId == "stringMatch":
                    field = trigger.pluginProps["fieldPopUp"]
                    pattern = trigger.pluginProps["stringPattern"]
                    self.logger.debug("\tChecking Device State %s for string: %s" % (field, pattern))
                    if device.states[field] == pattern:
                        self.logger.debug("\tExecuting Trigger %s (%d)" % (trigger.name, trigger.id))
                        indigo.trigger.execute(trigger)
                    else:
                        self.logger.debug("\tNo Match for Trigger %s (%d)" % (trigger.name, trigger.id))
                else:
                    self.logger.debug(
                        "\tUnknown Trigger Type %s (%d), %s" % (trigger.name, trigger.id, trigger.pluginTypeId))

                # pattern matching here

    ####################
    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorsDict = indigo.Dict()
        updateFrequency = valuesDict['updateFrequency']
        if len(updateFrequency) == 0 or int(updateFrequency) < 0 or int(updateFrequency) > 168:
            errorsDict['updateFrequency'] = u"Update frequency is invalid - enter number of hours between 0 and 168"

        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))

            self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "24")) * 60.0 * 60.0
            self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
            self.next_update_check = time.time()

    ########################################
    # Called for each enabled Device belonging to plugin
    # Verify connectivity to servers and start polling IMAP/POP servers here
    #
    def deviceStartComm(self, device):

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers >= kCurDevVersCount:
            self.logger.debug(device.name + u": Device Version is up to date")
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps

            encryptionType = device.pluginProps.get('encryptionType', "unknown")
            if encryptionType == "unknown":
                useSSL = device.pluginProps.get('useSSL', "false")
                if useSSL:
                    newProps["encryptionType"] = "SSL"
                else:
                    newProps["encryptionType"] = "None"
                self.logger.debug(device.name + u": created encryptionType property")

            if device.deviceTypeId == "imapAccount":
                useIDLE = device.pluginProps.get('useIDLE', "unknown")
                if useIDLE == "unknown":
                    newProps["useIDLE"] = "True"
                    self.logger.debug(device.name + u": created useIDLE property")

            pollingFrequency = device.pluginProps.get('pollingFrequency', "unknown")
            if pollingFrequency == "unknown":
                newProps["pollingFrequency"] = device.pluginProps.get('pollingFrequency', 15)
                self.logger.debug(device.name + u": created pollingFrequency property")

            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            self.logger.debug(u"Updated " + device.name + " to version " + str(kCurDevVersCount))

        else:
            self.logger.error(u"Unknown device version: " + str(instanceVers) + " for device " + device.name)

        if len(device.pluginProps) < 3:
            self.logger.error(u"Server \"%s\" is misconfigured - disabling" % device.name)
            indigo.device.enable(device, value=False)

        else:
            if device.id not in self.serverDict:
                self.logger.debug(u"Starting server: " + device.name)
                if device.deviceTypeId == "imapAccount":
                    self.serverDict[device.id] = IMAPServer(device)
                elif device.deviceTypeId == "popAccount":
                    self.serverDict[device.id] = POPServer(device)
                elif device.deviceTypeId == "smtpAccount":
                    self.serverDict[device.id] = SMTPServer(device)
                else:
                    self.logger.error(u"Unknown server device type: " + str(device.deviceTypeId))
            else:
                self.logger.debug(u"Duplicate Device ID: " + device.name)

    ########################################
    # Terminate communication with servers
    #
    def deviceStopComm(self, device):
        if device.id in self.serverDict:
            self.logger.debug(u"Stopping server: " + device.name)
            del self.serverDict[device.id]
        else:
            self.logger.debug(u"Unknown Device ID: " + device.name)

    ########################################

    def runConcurrentThread(self):

        try:
            while True:

                if (self.updateFrequency > 0.0) and (time.time() > self.next_update_check):
                    self.next_update_check = time.time() + self.updateFrequency
                    self.updater.checkForUpdate()

                for serverId, server in self.serverDict.items():
                    if server.pollCheck():
                        server.poll()

                # wait a minute and do it all again.
                self.sleep(60)

        except self.StopThread:
            pass

    ########################################
    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        self.logger.debug(u"validateDeviceConfigUi called")
        errorsDict = indigo.Dict()

        try:
            name = valuesDict['address']
            if len(name) < 1:
                raise
        except:
            errorsDict['address'] = u"Enter name of server"

        try:
            hostPort = valuesDict['hostPort']
            if len(hostPort) < 1:
                raise
        except:
            errorsDict['hostPort'] = u"Enter server port"

        try:
            poll = int(valuesDict['pollingFrequency'])
            if (poll < 0) or (poll > 1440):
                raise
        except:
            errorsDict['pollingFrequency'] = u"Polling frequency is invalid - enter a valid number (between 0 and 1440)"

        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    ########################################
    def validateActionConfigUi(self, valuesDict, typeId, devId):
        errorsDict = indigo.Dict()

        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ######################
    def sendEmailAction(self, pluginAction, smtpDevice):
        self.logger.debug(u"sendEmailAction queueing message '" + indigo.activePlugin.substitute(pluginAction.props["emailSubject"]) + "'")
        smtpServer = self.serverDict[smtpDevice.id]
        smtpServer.smtpQ.put(pluginAction)
        smtpServer.poll()

    ########################################
    # Menu Methods
    ########################################

    def checkForUpdates(self):
        self.updater.checkForUpdate()

    def updatePlugin(self):
        self.updater.update()

    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    def clearSMTPQueueMenu(self, valuesDict, typeId):
        try:
            deviceId = int(valuesDict["targetDevice"])
        except:
            self.logger.error(u"Bad Device specified for Clear SMTP Queue operation")
            return False

        for serverId, server in self.serverDict.items():
            if serverId == deviceId:
                self.logger.debug(u"Clearing SMTP Queue for " + server.device.name)
                server.clearQueue()
        return True

    def clearAllSMTPQueues(self):
        self.logger.debug(u"Clearing all SMTP Queues")
        for serverId, server in self.serverDict.items():
            if server.device.deviceTypeId == "smtpAccount":
                self.logger.debug(u"\tClearing SMTP Queue for " + server.device.name)
                server.clearQueue()

    def clearSMTPQueue(self, device):
        self.logger.debug(u"Clearing SMTP Queue for " + self.serverDict[device.deviceId].device.name)
        self.serverDict[device.deviceId].clearQueue()

    def pickSMTPServer(self, filter=None, valuesDict=None, typeId=0):
        retList = []
        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == "smtpAccount":
                retList.append((dev.id, dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def pollAllServers(self):
        self.logger.debug(u"Polling All Email Servers")
        for serverId, server in self.serverDict.items():
            self.logger.debug(u"Polling serverId: " + str(
                serverId) + ", serverTypeId: " + server.device.deviceTypeId + "(" + server.device.name + ")")
            server.poll()

    def pollServer(self, device):
        self.logger.debug(u"Polling Server: " + self.serverDict[device.deviceId].device.name)
        self.serverDict[device.deviceId].poll()

    def pickInboundServer(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for dev in indigo.devices.iter("self"):
            if (dev.deviceTypeId == "imapAccount") or (dev.deviceTypeId == "popAccount"):
                retList.append((dev.id, dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList
