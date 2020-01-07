import matplotlib


from glob import glob

import numpy as np
from itertools import *
from matplotlib import *
from matplotlib import pyplot as plt
from scipy.interpolate import griddata, NearestNDInterpolator
from scipy.weave import inline

from pyworkflow.protocol.params import (PointerParam, EnumParam, IntParam)

import pyworkflow.em as em
import pyworkflow.em.metadata as md
import pyworkflow.protocol.params as params
from cryomethods import Plugin
from cryomethods.convert import (loadMrc, saveMrc)
from xmipp3.convert import getImageLocation
from .protocol_base import ProtocolBase
import collections


PCA_THRESHOLD = 0
PCA_COUNT=1


class ProtLandscapePCA(ProtocolBase):
    _label = 'Control PCA'
    IS_2D = False
    IS_AUTOCLASSIFY = True
    def _initialize(self):
        """ This function is mean to be called after the
        working dir for the protocol have been set.
        (maybe after recovery from mapper)
        """
        self._createFilenameTemplates()
        self._createIterTemplates()


    def _createFilenameTemplates(self):
        """ Centralize how files are called for iterations and references. """
        self.levDir = self._getExtraPath()
        self.rLevDir = self._getExtraPath('lev_%(lev)02d/rLev_%(rLev)02d/')
        self.rLevIter = self.rLevDir + 'relion_it%(iter)03d_'
        # add to keys, data.star, optimiser.star and sampling.star
        myDict = {
            'input_star': self.levDir + 'input_rLev-%(rLev)03d.star',
            'outputData': self.levDir + 'output_data.star',
            'map': self.levDir + 'map_id-%(id)s.mrc',
            'avgMap': self.levDir+ 'map_average.mrc',
            'modelFinal': self.levDir + 'model.star',
            'relionMap': self.rLevDir + 'relion_it%(iter)03d_class%(ref3d)03d.mrc',
            'outputModel': self.levDir + 'output_model.star',
            'data': self.rLevIter + 'data.star',
            'rawFinalModel': self._getExtraPath('raw_final_model.star'),
            'rawFinalData': self._getExtraPath('raw_final_data.star'),
            'finalModel': self._getExtraPath('final_model.star'),
            'finalData': self._getExtraPath('final_data.star'),
            'finalAvgMap': self._getExtraPath('map_average.mrc'),
            'optimiser': self.rLevIter + 'optimiser.star',
            'all_avgPmax_xmipp': self._getTmpPath('iterations_avgPmax_xmipp.xmd'),
            'all_changes_xmipp': self._getTmpPath(
                'iterations_changes_xmipp.xmd')
                 }
        for key in self.FILE_KEYS:
            myDict[key] = self.rLevIter + '%s.star' % key
            key_xmipp = key + '_xmipp'
            myDict[key_xmipp] = self.rLevDir + '%s.xmd' % key
        # add other keys that depends on prefixes
        for p in self.PREFIXES:
            myDict['%smodel' % p] = self.rLevIter + '%smodel.star' % p
            myDict[
                '%svolume' % p] = self.rLevDir + p + 'class%(ref3d)03d.mrc:mrc'

        self._updateFilenamesDict(myDict)

    def _createIterTemplates(self, rLev=None):
        """ Setup the regex on how to find iterations. """
        rLev = self._rLev if rLev is None else rLev
        print("level rLev in _createIterTemplates:", self._level, rLev)

        self._iterTemplate = self._getFileName('data', lev=self._level,
                                               rLev=rLev,
                                               iter=0).replace('000', '???')
        # Iterations will be identify by _itXXX_ where XXX is the iteration
        # number and is restricted to only 3 digits.
        self._iterRegex = re.compile('_it(\d{3,3})_')
        self._classRegex = re.compile('_class(\d{2,2}).')

    # -------------------------- DEFINE param functions ------------------------
    def _defineParams(self, form):
        form.addSection(label='Input')
        form.addParam('inputVolumes', params.PointerParam,
                      pointerClass='SetOfVolumes',
                      important=True,
                      label='Input volumes',
                      help='Initial reference 3D maps')
        form.addParam('thresholdMode', EnumParam, choices=['thr', 'pcaCount'],
                      default=PCA_THRESHOLD,
                      label='Cut-off mode',
                      help='Threshold value will allow you to select the\n'
                           'principle components above this value.\n'
                           'sCut will allow you to select number of\n'
                           'principle components you want to select.')
        form.addParam('thr', params.FloatParam, default=0.95,
                      important=True,
                      condition='thresholdMode==%d' % PCA_THRESHOLD,
                      label='THreshold percentage')
        form.addParam('pcaCount', params.FloatParam, default=2,
                      label="count of PCA",
                      condition='thresholdMode==%d' % PCA_COUNT,
                      help='Number of PCA you want to select.')

        form.addParam('addWeights', params.FileParam, label="Weight File path",
                      allowsNull=True,
                      help='Specify a path to weights for volumes.')

        form.addParallelSection(threads=0, mpi=0)

    # --------------------------- INSERT steps functions ------------------------
    def _insertAllSteps(self):
        self._insertFunctionStep('analyzePCAStep')

    #-------------------------step function-----------------------------------

    def _getAverageVol(self):
        self._createFilenameTemplates()
        Plugin.setEnviron()

        inputObj = self.inputVolumes.get()
        listVol = []
        for i in inputObj:

            a = getImageLocation(i).split(':')[0]
            listVol.append(a)

        # listVol = self._getPathMaps() if not bool(listVol) else listVol
        print (listVol, "listVolll")
        print('creating average map: ', listVol)
        avgVol = self._getFileName('avgMap')
        print (avgVol, "avgVol")

        print('alignining each volume vs. reference')
        for vol in listVol:
            print (vol, "vol2")
            npVol = loadMrc(vol, writable=False)

            if vol == listVol[0]:
                dType = npVol.dtype
                npAvgVol = np.zeros(npVol.shape)
            npAvgVol += npVol

        print (npAvgVol, "npAvgVol1")
        npAvgVol = np.divide(npAvgVol, len(listVol))
        print('saving average volume')
        saveMrc(npAvgVol.astype(dType), avgVol)

    def getParticlesPca(self):
        z_part= np.loadtxt(self.addWeights.get())
        print (z_part, "z_part")
        return z_part


    def analyzePCAStep(self):
        self._createFilenameTemplates()
        Plugin.setEnviron()

        row = md.Row()
        refMd = md.MetaData()

        inputObj = self.inputVolumes.get()

        fnIn= []
        for i in inputObj:
            a = getImageLocation(i).split(':')[0]
            fnIn.append(a)

        for vol in fnIn:
            row.setValue(md.RLN_MLMODEL_REF_IMAGE, vol)
            row.addToMd(refMd)
        refMd.write(self._getRefStar())
        print (fnIn, "fninn")

        listVol = fnIn

        print (len(self.inputVolumes.get()), "self.inputVolumes.get()")
        self._getAverageVol()

        avgVol = self._getFileName('avgMap')
        npAvgVol = loadMrc(avgVol, False)
        dType = npAvgVol.dtype
        iniVolNp = loadMrc(listVol[0], False)
        dim = iniVolNp.shape[0]
        lenght = dim ** 3
        cov_matrix = []
        for vol in listVol:
            volNp = loadMrc(vol, False)
            volList = volNp.reshape(lenght)

            row = []
            # Now, using diff volume to estimate PCA
            b = volList - npAvgVol.reshape(lenght)
            for j in listVol:
                npVol = loadMrc(j, writable=False)
                volList_a = npVol.reshape(lenght)
                print (len(volList_a), "volist(1)_length")
                volList_two = volList_a - npAvgVol.reshape(lenght)
                temp_a= np.corrcoef(volList_two, b).item(1)
                print (temp_a, "temp_a")
                row.append(temp_a)
            cov_matrix.append(row)

        print (cov_matrix, "covMatrix")
        u, s, vh = np.linalg.svd(cov_matrix)
        vhDel = self._getvhDel(vh, s)
        # -------------NEWBASE_AXIS-------------------------------------------
        counter = 0

        for i in vhDel.T:
            base = np.zeros(lenght)
            for (a, b) in izip(listVol,i):
                print (len(a), "volist")
                volInp = loadMrc(a, False)
                volInpR = volInp.reshape(lenght)
                print (b.shape, "vhdel")
                base += volInpR*b
                volBase = base.reshape((dim, dim, dim))
                print (volBase.shape, "volBase")
            nameVol = 'volume_base_%02d.mrc' % (counter)
            print (counter, "counter")
            print('-------------saving map %s-----------------' % nameVol)
            saveMrc(volBase.astype(dType),self._getExtraPath(nameVol))
            counter += 1

        matProj = []
        baseMrc = self._getExtraPath("*.mrc")
        baseMrcFile = glob(baseMrc)
        for vol in listVol:
            volNp = loadMrc(vol, False)
            volRow = volNp.reshape(lenght)
            volInputTwo = volRow - npAvgVol.reshape(lenght)
            row_one = []
            for j in baseMrcFile:
                npVol = loadMrc(j, writable=False)
                volBaseTwo= npVol.reshape(lenght)
                j_trans = volBaseTwo.transpose()
                matrix_two = np.dot(volInputTwo, j_trans)
                row_one.append(matrix_two)
            matProj.append(row_one)
        print (len(matProj), "len_mat_one")
        print (len(vhDel), "len_2vhDel")



        # obtaining original volumes--------------------------------------------
        baseMrc = self._getExtraPath("*.mrc")
        baseMrcFile = glob(baseMrc)
        print (baseMrcFile, "base mrcfile")
        os.makedirs(self._getExtraPath('original_vols'))
        orignCount=0
        for i in matProj:
            vol = np.zeros((dim, dim,dim))
            for a, b in zip(baseMrcFile, i):
                print (a, "volist")
                print (b, "matproj")
                volNpo = loadMrc(a, False)
                print (volNpo.shape, "volList")
                vol += volNpo * b
            finalVol= vol + npAvgVol
            nameVol = 'volume_reconstructed_%02d.mrc' % (orignCount)
            print('-------------saving original_vols %s-----------------' % nameVol)
            saveMrc(finalVol.astype(dType), self._getExtraPath('original_vols', nameVol))
            orignCount += 1


        # difference b/w input vol and original vol-----------------------------
        reconstMrc = self._getExtraPath("original_vols","*.mrc")
        reconstMrcFile = glob(reconstMrc)
        diffCount=0
        os.makedirs(self._getExtraPath('volDiff'))
        for a, b in zip(reconstMrcFile, listVol):
            volRec = loadMrc(a, False)
            volInpThree = loadMrc(b, False)
            volDiff= volRec - volInpThree
            # print (volDiff, "volDiff")
            nameVol = 'volDiff_%02d.mrc' % (diffCount)
            print('-------------saving original_vols %s-----------------' % nameVol)
            saveMrc(volDiff.astype(dType), self._getExtraPath('volDiff', nameVol))
            diffCount += 1

        #save coordinates:
        os.makedirs(self._getExtraPath('Coordinates'))
        coorPath = self._getExtraPath('Coordinates')


        mat_file = os.path.join(coorPath, 'matProj_splic')
        coordNumpy= np.save(mat_file, matProj)

    # -------------------------- UTILS functions ------------------------------
    def _getVolume(self):
        self._createFilenameTemplates()

        Plugin.setEnviron()

        row = md.Row()
        refMd = md.MetaData()

        ih = em.ImageHandler()
        inputObj = self.inputVolumes.get()

        fnIn = []
        for i in inputObj:
            a = getImageLocation(i).split(':')[0]
            fnIn.append(a)

        for vol in fnIn:
            row.setValue(md.RLN_MLMODEL_REF_IMAGE, vol)
            row.addToMd(refMd)
        refMd.write(self._getRefStar())

        print (fnIn, "fninn")

        listVol = fnIn
        self._getAverageVol(listVol)

        avgVol = self._getFileName('avgMap')
        npAvgVol = loadMrc(avgVol, False)
        dType = npAvgVol.dtype
        volNp = loadMrc(listVol.__getitem__(0), False)
        dim = volNp.shape[0]
        lenght = dim ** 3
        cov_matrix = []
        volL = []
        for vol in listVol:
            volNp = loadMrc(vol, False)

            volList = volNp.reshape(lenght)
            volL.append(volList)

    def _getRefStar(self):
        return self._getExtraPath("input_references.star")



    def _getPathMaps(self):
        inputObj = self.inputVolumes.get()
        filesPath = []
        for i in inputObj:
            a = getImageLocation(i)
            filesPath.append(a)

        print (filesPath, "fninn")
        return sorted(glob(filesPath))

    def _createMFile(self, matrix, name='matrix.txt'):
        print (name, "name")
        f = open(name, 'w')        # f = open(name, 'w')
        for list in matrix:
            s = "%s\n" % list
            f.write(s)
        f.close()

    def _getClassId(self, volFile):
        result = None
        s = self._classRegex.search(volFile)
        if s:
            result = int(s.group(1)) # group 1 is 2 digits class number
        return self.volDict[result]


    def _getvhDel(self, vh, s):

        if self.thresholdMode == PCA_THRESHOLD:
            thr= self.thr.get()
            if thr < 1:
                cuttOffMatrix = sum(s) * thr
                sCut = 0

                print('cuttOffMatrix & s: ', cuttOffMatrix, s)
                for i in s:
                    if cuttOffMatrix > 0:
                        print("Pass, i = %s " % i)
                        cuttOffMatrix = cuttOffMatrix - i
                        sCut += 1
                    else:
                        break
                print('sCut: ', sCut)

                vhDel = self._geteigen(vh, sCut, s)
                return vhDel
            else:
                os.makedirs(self._getExtraPath('EigenFile'))
                eigPath = self._getExtraPath('EigenFile')
                eigValsFile = os.path.join(eigPath, 'eigenvalues')
                np.save(eigValsFile, s)
                eignValData = np.load(
                    self._getExtraPath('EigenFile', 'eigenvalues.npy'))
                print (eignValData, "eignValData")

                eigVecsFile = os.path.join(eigPath, 'eigenvectors')
                np.save(eigVecsFile, vh)
                eignVecData = np.load(
                    self._getExtraPath('EigenFile', 'eigenvectors.npy'))
                print (eignVecData, "eignVecData")
                vhdelPath = os.path.join(eigPath, 'matrix_vhDel')
                np.save(vhdelPath, vh.T)
                vhDelData = np.load(
                    self._getExtraPath('EigenFile', 'matrix_vhDel.npy'))
                print (vhDelData, "vhDelData")
                return vh.T
        else:

            sCut= int(self.pcaCount.get())
            vhDel = self._geteigen(vh, sCut, s)
            return vhDel

    def _geteigen(self, vh, sCut, s):
        os.makedirs(self._getExtraPath('EigenFile'))
        eigPath = self._getExtraPath('EigenFile')
        eigValsFile = os.path.join(eigPath, 'eigenvalues')
        np.save(eigValsFile, s)
        eignValData = np.load(
            self._getExtraPath('EigenFile', 'eigenvalues.npy'))
        print (eignValData, "eignValData")

        eigVecsFile = os.path.join(eigPath, 'eigenvectors')
        np.save(eigVecsFile, vh)
        eignVecData = np.load(
            self._getExtraPath('EigenFile', 'eigenvectors.npy'))
        print (eignVecData, "eignVecData")

        vhDel = np.transpose(np.delete(vh, np.s_[sCut:vh.shape[1]], axis=0))
        vhdelPath = os.path.join(eigPath, 'matrix_vhDel')
        np.save(vhdelPath, vhDel)
        vhDelData = np.load(self._getExtraPath('EigenFile', 'matrix_vhDel.npy'))

        print(' this is the matrix "vhDel": ', vhDel)
        print (len(vhDel), "vhDel_length")
        return vhDel

    def _getPcaCount(self, s):
        cuttOffMatrix = sum(s) * 0.95
        sCut = 0

        print('cuttOffMatrix & s: ', cuttOffMatrix, s)
        for i in s:
            print('cuttOffMatrix: ', cuttOffMatrix)
            if cuttOffMatrix > 0:
                print("Pass, i = %s " % i)
                cuttOffMatrix = cuttOffMatrix - i
                sCut += 1
            else:
                break
        print('sCut: ', sCut)
        return sCut




    def _validate(self):
        errors = []
        return errors
