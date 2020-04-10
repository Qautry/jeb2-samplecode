# -*- coding: utf-8 -*-

"""
This JEB script is a string decryptor for the obfuscated Triada malware. Decrypted strings will substitute the encrypted parts or be added as field comments in your Java classes.
Author: Ruoxiao Wang

The script can be tested on Triada Application MD5 592fa585b64412e31b3da77b1e825208
- The target class path: com/zmpk/a/a (contains all encrypted byte arrays and two decryptors)
- The main target class is in: com/zmpk/a/c (where the substitution happens)

*** CUSTOMIZE the attributes TARGET_CLASS_NAME, TARGET_CLASS_NAME_MAIN, DECRYPTOR_1_NAME_KEY, DECRYPTOR_2_NAME_KEY and DECRYPTOR_MAIN_KEY to decrypt strings located in other classes ***

How to run the script:
(1) (Optional) Copy TriadaStringDecryptor.py to your jeb scripts/ folder
(2) Start the JEB application and open the Triada file
(3) Open the target class (path: com/zmpk/a/a)
(4) Press Q to decompile the class
(5) Open the main target class (path: com/zmpk/a/c)
(6) Press Q to decompile the class
(7) Select: File -> Scripts -> Run Script -> TriadaStringDecryptor.py and click open
(8) Decrypted strings will be added to the target class as comments or substitute the encrypted parts in the main target class

Several Objects and APIs are used:
(1) IScript: Interface for client's scripts.
(2) IRuntimeProject: A runtime project represents a loaded instance of a JEB project.
(3) ICodeUnit: Base interface for units handling binary code, such as bytecode, opcodes, object files, executable files.
(4) IJavaSourceUnit: Definition of a source unit representing a Java class in the form of an Abstract Syntax Tree.
(5) IJavaClass: Java AST interface to represent a Java class. Class elements contain other classes (inner classes), fields, and methods.
(6) IJavaConstantFactory: Builder for Java AST constants.
(7) RuntimeProjectUtil: A collection of utility methods to navigate and act on JEB projects.
(8) ICodeField: A filed object.
(9) IJavaMethod: Java AST interface to represent Java methods.
(10) IJavaBlock: Java AST interface to represent a sequence of statements.
(11) IJavaAssignment: Java AST interface to represent assignments.
(12) Actions: This class defines well-known actions.
(13) QUERY_XREFS: Query cross-references action.
(14) COMMENT: Comment action.
(15) prepareExecution: Prepare the execution of an action. Clients must call this method before attempting to call.
(16) executeAction: True if the execution was successful. 
* For detailed information, please refer to the PNF API document.
* Detailed comments are added to the script TriadaStringDecryptor.py
"""

from com.pnfsoftware.jeb.client.api import IScript, IGraphicalClientContext
from com.pnfsoftware.jeb.core import RuntimeProjectUtil
from com.pnfsoftware.jeb.core.actions import Actions, ActionContext, ActionCommentData, ActionXrefsData
from com.pnfsoftware.jeb.core.events import JebEvent, J
from com.pnfsoftware.jeb.core.output import AbstractUnitRepresentation, UnitRepresentationAdapter
from com.pnfsoftware.jeb.core.units.code import ICodeUnit, ICodeItem
from com.pnfsoftware.jeb.core.units.code.java import IJavaSourceUnit, IJavaStaticField, IJavaNewArray, IJavaConstant, IJavaCall, IJavaField, IJavaMethod, IJavaClass


class TriadaStringDecryptor(IScript):

  # NOTE: USERS MUST CUSTOMIZE THESE FIELDS in order to decrypt strings located in other classes
  TARGET_CLASS_NAME = "Lcom/zmpk/a/a;" # Specify the name of target class
  TARGET_CLASS_NAME_MAIN = "Lcom/zmpk/a/c;" # Specify the name of main target class
  DECRYPTOR_1_NAME_KEY = ("a", 44) # Specify the name and key of decryptor 1
  DECRYPTOR_2_NAME_KEY = ("b", 43) # Specify the name and key of decryptor 2
  DECRYPTOR_MAIN_KEY = -1 # Specify the key of main decryptor

  def run(self, ctx):

    engctx = ctx.getEnginesContext()
    if not engctx:
      print('Back-end engines not initialized')
      return

    projects = engctx.getProjects()
    if not projects:
      print('There is no opened project')
      return

    project = projects[0] # Get current project(IRuntimeProject)
    print('Decompiling code units of %s...' % project)

    self.codeUnit = RuntimeProjectUtil.findUnitsByType(project, ICodeUnit, False)[0] # Get the current codeUnit(ICodeUnit)

    # enumerate the decompiled classes, find and process the target class
    units = RuntimeProjectUtil.findUnitsByType(project, IJavaSourceUnit, False)

    targetClass = "" # Taget class
    targetClassMain = "" # Main taget class

    for unit in units:
      javaClass = unit.getClassElement() # Get a reference to the Java class defined in this unit

      if javaClass.getName() == self.TARGET_CLASS_NAME: # If the current class is the target class, store the target class
        targetClass = javaClass
      if javaClass.getName() == self.TARGET_CLASS_NAME_MAIN: # If the current class is the main target class, store the main target class
        targetClassMain = javaClass
        self.cstbuilder = unit.getFactories().getConstantFactory()

    self.processTargetClass(targetClass)
    if self.dic:
      self.processMainTargetClass(targetClassMain) # If dic is not empty, which means some variables are called by other class(main target class), we should run substitStr() method

  def processTargetClass(self, javaClass):
    self.dic = {} # Store the key value pairs. Key: variable name; Value: decrypted string
    # eg: public static final byte[] b
    # Key: b
    # Value: decrypted string of b

    wanted_flags = ICodeItem.FLAG_PRIVATE|ICodeItem.FLAG_STATIC|ICodeItem.FLAG_FINAL # Set the flag: "private" && "static" && "final"

    # Get the static constructor
    statConst = self.getStaticConstructor(javaClass)
    
    for i in range(javaClass.getFields().size()):
      fsig = javaClass.getFields().get(i).getSignature()
      
      # get the variable name
      x = fsig.find('->') + 2
      valName = fsig[x : x + 1]

      if fsig.endswith(':[B'):
        f = self.codeUnit.getField(fsig) # Get the field of the ith static final variable
        s0 = statConst.getBody().get(i) # Get the ith assignment in static constructor
        encbytes = [] # Used to store the elements of the current byte array

        if isinstance(s0.getLeft(), IJavaStaticField) and s0.getLeft().getField().getSignature() == f.getSignature(True):
          array = s0.getRight()

          if isinstance(array, IJavaNewArray):
            for v in array.getInitialValues(): # Get the list of initial values of the byte array
              optElement = 0 # Used to store the element decrypted by the decryptor

              if isinstance(v, IJavaCall): # Determine if the element is an instance of an IJavaCall
                mname = v.getMethod().getName() # Get the name of the method(call method, decryptor)
                arrayArguments = [] # Used to store the arguments of the method

                # Get decryptor name and store the arguments
                if mname == "byteValue":
                  # If the decryptor name is "byteValue", which means the method is like "a.b(74).byteValue()", we need to get the first part: "a.b(74)", 
                  # then extract the real method name "b"
                  mname = v.getArguments().get(0).getMethod().getName();
                  # Get the arguments of the method

                  for arg in v.getArguments().get(0).getArguments():
                    if isinstance(arg, IJavaConstant):
                      arrayArguments.append(arg.getInt())
                else:
                  # Get the arguments of the method
                  for arg in v.getArguments():
                    if isinstance(arg, IJavaConstant):
                      arrayArguments.append(arg.getInt())

                # Get the corresponding decryptor and decrypt the element
                if mname == self.DECRYPTOR_1_NAME_KEY[0]:
                  if len(arrayArguments) == 1:
                    optElement = self.decryptor1(arrayArguments[0])
                if mname == self.DECRYPTOR_2_NAME_KEY[0]:
                  if len(arrayArguments) == 1:
                    optElement = self.decryptor2(arrayArguments[0])
                encbytes.append(optElement)
              else:
                encbytes.append(v.getByte())

        decrypted_string = self.decryptorMain(encbytes) # Descrpt the byte array into string
        self.setOrStoreDecryptedStr(self.codeUnit, f.getItemId(), decrypted_string, valName) # Add the decryped strings as comments directly or store them to dictionary

    print('*********************** Finished ***********************')

  def processMainTargetClass(self, javaClass):
    # Get the static constructor
    statConst = self.getStaticConstructor(javaClass)
    
    for i in range(javaClass.getFields().size()):
      fsig = javaClass.getFields().get(i).getSignature()
      
      if fsig.endswith('String;'):
        f = self.codeUnit.getField(fsig) # Get the field of the ith static final variable
        s0 = statConst.getBody().get(i) # Get the ith assignment in static constructor
        if isinstance(s0.getLeft(), IJavaStaticField) and s0.getLeft().getField().getSignature() == f.getSignature(True):
          method = s0.getRight()
          if isinstance(method, IJavaCall):
            valName = method.getArguments().get(0).getField().getName()
            s0.replaceSubElement(s0.getSubElements().get(1), self.cstbuilder.createString(self.dic.get(valName)))

  def setOrStoreDecryptedStr(self, unit, itemId, comment, key):
    data = ActionXrefsData()
    if unit.prepareExecution(ActionContext(unit, Actions.QUERY_XREFS, itemId, None), data):
      if data.getAddresses().size() > 1: # If the variable is called by other class(main target class)
        self.dic[key] = comment # Store the key value pair into the dictionary
      else:
        self.addComments(self.codeUnit, itemId, comment) # If the variable is not called by other class(main target class), add the decrypted string as comment directly
        return "NULL"

  def addComments(self, unit, itemId, comment):
    data = ActionCommentData() # Create a new instance of ActionCommentData
    data.setNewComment(comment) # Add the decrypted string as comment to data
    address = unit.getAddressOfItem(itemId)
    # Set the comment
    ctx = ActionContext(unit, Actions.COMMENT, itemId, address)
    if unit.prepareExecution(ctx, data):
      r = unit.executeAction(ctx, data)
      if not r:
        print('Cannot set comment at address %s' % address)

  def getStaticConstructor(self, javaClass): # Get the static constructor
    for statConst in javaClass.getMethods():
      if statConst.getName() == '<clinit>':
        return statConst

  def decryptor1(self, eachByte):
    eachByte += self.DECRYPTOR_1_NAME_KEY[1]
    return eachByte

  def decryptor2(self, eachByte):
    eachByte += self.DECRYPTOR_2_NAME_KEY[1]
    return eachByte

  def decryptorMain(self, encbytes):
    r = ''
    for i in encbytes:
      temp = i + self.DECRYPTOR_MAIN_KEY
      r += chr(temp & 0xFF)
    return r