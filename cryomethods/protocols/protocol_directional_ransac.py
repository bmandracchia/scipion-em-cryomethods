# **************************************************************************
# *
# * Authors:         Javier Vargas (jvargas@cnb.csic.es) (2016)
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 2 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'jmdelarosa@cnb.csic.es'
# *
# **************************************************************************



from pyworkflow.protocol.params import (PointerParam, FloatParam, STEPS_PARALLEL,EnumParam,
                                        StringParam, BooleanParam, IntParam,LabelParam, PathParam,LEVEL_ADVANCED)

import pyworkflow.em.metadata as md
from cryomethods.protocols import ProtDirectionalPruning

#from .protocol_base import ProtocolBase
from pyworkflow.utils.path import cleanPath,makePath

from pyworkflow.em.protocol import ProtClassify3D ,ProtAnalysis3D

from cryomethods.convert import writeSetOfParticles,splitInCTFGroups,rowToAlignment
from pyworkflow.em.metadata.utils import getSize
import xmippLib
import math
import numpy as np
import random
from cryomethods.convert import  relionToLocation, loadMrc, saveMrc,alignVolumes, applyTransforms
from cryomethods import Plugin
from pyworkflow.em.convert import ImageHandler
from matplotlib import *
from matplotlib import pyplot as plt
import matplotlib.cm as cm
from scipy.interpolate import griddata


import random
import pyworkflow.em as em
from os.path import join, exists
from os import remove



import cryomethods.convertXmp as convXmp


class ProtClass3DRansac(ProtClassify3D,ProtDirectionalPruning ,ProtAnalysis3D):

    """    
    Performs 3D classification of input particles with previous alignment
    """
    _label = 'directional_ransac'

    CL2D = 0
    ML2D = 1
    RL2D = 2
    Kmeans = 3
    AP = 4

    
    def __init__(self, *args, **kwargs):
        ProtClassify3D.__init__(self, *args, **kwargs)
        ProtAnalysis3D.__init__(self, *args, **kwargs)
        ProtDirectionalPruning.__init__(self, *args, **kwargs)
        #ProtocolBase.__init__(self, *args, **kwargs)
        
    #--------------------------- DEFINE param functions --------------------------------------------   
    def _defineParams(self, form):

        form.addSection(label='Input')
        form.addParam('inputVolume', PointerParam, pointerClass='Volume',
                      label="Input volume",  
                      help='Select the input volume.')     
        form.addParam('inputParticles', PointerParam,
                      pointerClass='SetOfParticles', pointerCondition='hasAlignment',
                      label="Input particles", important=True,
                      help='Select the input projection images.')
        form.addParam('backRadius', IntParam, default=-1,
                      label='Mask radius',
                      help='Pixels outside this circle are assumed to be noise')
        form.addParam('targetResolution', FloatParam, default=10, label='Target resolution (A)', expertLevel=LEVEL_ADVANCED,
                      help='Expected Resolution of the initial 3D classes obtained by the 2D classes. You should have a good' 
                      'reason to modify the 10 A value')

        form.addParam('symmetryGroup', StringParam, default='c1',
                      label="Symmetry group", 
                      help='See [[Xmipp Symmetry][http://www2.mrc-lmb.cam.ac.uk/Xmipp/index.php/Conventions_%26_File_formats#Symmetry]] page '
                           'for a description of the symmetry format accepted by Xmipp') 

        form.addSection(label='Directional Classes')

        form.addParam('angularSampling', FloatParam, default=5, label='Angular sampling', expertLevel=LEVEL_ADVANCED, help="In degrees")
        form.addParam('angularDistance', FloatParam, default=10, label='Angular distance', expertLevel=LEVEL_ADVANCED,
                      help="In degrees. An image belongs to a group if its distance is smaller than this value")
        form.addParam('noOfParticles', IntParam, default=25,
                      expertLevel=LEVEL_ADVANCED,
                      label='Number of Particles',
                      help='minimum number of particles required to do 2D'
                           'Classification')
        form.addParam('directionalClasses', IntParam, default=2,
                      label='Number of 2D classes in per directions',
                      expertLevel=LEVEL_ADVANCED)
        groupClass2D = form.addSection(label='2D Classification')
        groupClass2D.addParam('Class2D', EnumParam, choices=['ML2D','CL2D','RL2D'], default= 2,
                     label="2D classification method", display=EnumParam.DISPLAY_COMBO,
                     help='2D classification algorithm used to be applied to the directional classes. \n ')
        
        groupClass2D.addParam('CL2D_it', IntParam, default=20, condition='Class2D == 0',
                     label='number of iterations',
                     help='This is the radius (in pixels) of the spherical mask ')
        
        groupClass2D.addParam('CL2D_shift', IntParam, default=5, condition='Class2D == 0',
                     label='Maximum allowed shift',
                     help='Maximum allowed shift ')
        groupClass2D.addParam('maxIters', IntParam, default=100,
                      label='Maximum number of iterations',
                      help='If the convergence has not been reached after '
                           'this number of iterations, the process will be '
                           'stopped.',
                      condition='Class2D==1')
        form.addParam('numberOfIterations', IntParam, default=25,
                      label='Number of iterations',
                      condition='Class2D==2',
                      help='Number of iterations to be performed. Note '
                           'that the current implementation does NOT '
                           'comprise a convergence criterium. Therefore, '
                           'the calculations will need to be stopped '
                           'by the user if further iterations do not yield '
                           'improvements in resolution or classes. '
                           'If continue option is True, you going to do '
                           'this number of new iterations (e.g. if '
                           '*Continue from iteration* is set 3 and this '
                           'param is set 25, the final iteration of the '
                           'protocol will be the 28th.')
        form.addParam('randomIteration', IntParam, default=5,
                      label='Number of random iterations',
                      help="Number of random iterations to be performed.One"
                           " class average will be randomly selected per "
                           "iteration in all direction.This number corresponds"
                           " to 3D classes will be obtained")
        form.addSection(label='Optimisation')
        form.addParam('regularisationParamT', IntParam,
                      default=2,
                      label='Regularisation parameter T',
                      condition='Class2D==2',
                      help='Bayes law strictly determines the relative '
                           'weight between the contribution of the '
                           'experimental data and the prior. '
                           'However, in practice one may need to adjust '
                           'this weight to put slightly more weight on the '
                           'experimental data to allow optimal results. '
                           'Values greater than 1 for this regularisation '
                           'parameter (T in the JMB2011 paper) put more '
                           'weight on the experimental data. Values around '
                           '2-4 have been observed to be useful for 3D '
                           'refinements, values of 1-2 for 2D refinements. '
                           'Too small values yield too-low resolution '
                           'structures; too high values result in '
                           'over-estimated resolutions and overfitting.')
        form.addParam('copyAlignment', BooleanParam, default=True,
                      label='Consider previous alignment?',
                      condition='Class2D==2',

                      help='If set to Yes, then alignment information from'
                           ' input particles will be considered.')
        form.addParam('alignmentAsPriors', BooleanParam, default=False,
                      condition='Class2D==2',
                      label='Consider alignment as priors?',
                      help='If set to Yes, then alignment information from '
                           'input particles will be considered as PRIORS. This '
                           'option is mandatory if you want to do local '
                           'searches')
        form.addParam('fillRandomSubset', BooleanParam, default=False,
                      condition='Class2D==2',
                      label='Consider random subset value?',
                      help='If set to Yes, then random subset value '
                           'of input particles will be put into the'
                           'star file that is generated.')
        form.addParam('maskDiameterA', IntParam, default=-1,
                      condition='Class2D==2',
                      label='Particle mask diameter (A)',
                      help='The experimental images will be masked with a '
                           'soft circular mask with this <diameter>. '
                           'Make sure this diameter is not set too small '
                           'because that may mask away part of the signal! If '
                           'set to a value larger than the image size no '
                           'masking will be performed.\n\n'
                           'The same diameter will also be used for a '
                           'spherical mask of the reference structures if no '
                           'user-provided mask is specified.')
        form.addParam('referenceClassification', BooleanParam, default=True,
                      condition='Class2D==2',
                      label='Perform reference based classification?')
        form.addSection(label='Sampling')
        form.addParam('doImageAlignment', BooleanParam, default=True,
                      label='Perform Image Alignment?',
                      condition='Class2D==2',
                      )
        form.addParam('inplaneAngularSamplingDeg', FloatParam, default=5,
                      label='In-plane angular sampling (deg)',
                      condition='Class2D==2 and doImageAlignment',

                      help='The sampling rate for the in-plane rotation '
                           'angle (psi) in degrees.\n'
                           'Using fine values will slow down the program. '
                           'Recommended value for\n'
                           'most 2D refinements: 5 degrees. \n\n'
                           'If auto-sampling is used, this will be the '
                           'value for the first \niteration(s) only, and '
                           'the sampling rate will be increased \n'
                           'automatically after that.')
        form.addParam('offsetSearchRangePix', FloatParam, default=5,

                      condition='Class2D==2 and doImageAlignment',
                      label='Offset search range (pix)',
                      help='Probabilities will be calculated only for '
                           'translations in a circle with this radius (in '
                           'pixels). The center of this circle changes at '
                           'every iteration and is placed at the optimal '
                           'translation for each image in the previous '
                           'iteration.')
        form.addParam('offsetSearchStepPix', FloatParam, default=1.0,

                      condition='Class2D==2 and doImageAlignment',
                      label='Offset search step (pix)',
                      help='Translations will be sampled with this step-size '
                           '(in pixels). Translational sampling is also done '
                           'using the adaptive approach. Therefore, if '
                           'adaptive=1, the translations will first be '
                           'evaluated on a 2x coarser grid.')
        form.addSection(label='Compute')
        form.addParam('allParticlesRam', BooleanParam, default=False,
                      label='Pre-read all particles into RAM?',
                      condition='Class2D==2',
                      help='If set to Yes, all particle images will be '
                           'read into computer memory, which will greatly '
                           'speed up calculations on systems with slow '
                           'disk access. However, one should of course be '
                           'careful with the amount of RAM available. '
                           'Because particles are read in '
                           'float-precision, it will take \n'
                           '( N * (box_size)^2 * 4 / (1024 * 1024 '
                           '* 1024) ) Giga-bytes to read N particles into '
                           'RAM. For 100 thousand 200x200 images, that '
                           'becomes 15Gb, or 60 Gb for the same number of '
                           '400x400 particles. Remember that running a '
                           'single MPI slave on each node that runs as '
                           'many threads as available cores will have '
                           'access to all available RAM.\n\n'
                           'If parallel disc I/O is set to No, then only '
                           'the master reads all particles into RAM and '
                           'sends those particles through the network to '
                           'the MPI slaves during the refinement '
                           'iterations.')
        form.addParam('scratchDir', PathParam,

                      condition='Class2D==2 and not allParticlesRam',
                      label='Copy particles to scratch directory: ',
                      help='If a directory is provided here, then the job '
                           'will create a sub-directory in it called '
                           'relion_volatile. If that relion_volatile '
                           'directory already exists, it will be wiped. '
                           'Then, the program will copy all input '
                           'particles into a large stack inside the '
                           'relion_volatile subdirectory. Provided this '
                           'directory is on a fast local drive (e.g. an '
                           'SSD drive), processing in all the iterations '
                           'will be faster. If the job finishes '
                           'correctly, the relion_volatile directory will '
                           'be wiped. If the job crashes, you may want to '
                           'remove it yourself.')
        form.addParam('combineItersDisc', BooleanParam, default=False,
                      label='Combine iterations through disc?',
                      condition='Class2D==2',
                      help='If set to Yes, at the end of every iteration '
                           'all MPI slaves will write out a large file '
                           'with their accumulated results. The MPI '
                           'master will read in all these files, combine '
                           'them all, and write out a new file with the '
                           'combined results. All MPI slaves will then '
                           'read in the combined results. This reduces '
                           'heavy load on the network, but increases load '
                           'on the disc I/O. This will affect the time it '
                           'takes between the progress-bar in the '
                           'expectation step reaching its end (the mouse '
                           'gets to the cheese) and the start of the '
                           'ensuing maximisation step. It will depend on '
                           'your system setup which is most efficient.')
        form.addParam('doGpu', BooleanParam, default=True,
                      label='Use GPU acceleration?',
                      condition='Class2D==2',
                      help='If set to Yes, the job will try to use GPU '
                           'acceleration.')
        form.addParam('gpusToUse', StringParam, default='',
                      label='Which GPUs to use:',
                      condition='Class2D==2 and doGpu',
                      help='This argument is not necessary. If left empty, '
                           'the job itself will try to allocate available '
                           'GPU resources. You can override the default '
                           'allocation by providing a list of which GPUs '
                           '(0,1,2,3, etc) to use. MPI-processes are '
                           'separated by ":", threads by ",". '
                           'For example: "0,0:1,1:0,0:1,1"')
        form.addParam('useParallelDisk', BooleanParam, default=True,
                      label='Use parallel disc I/O?',
                      condition='Class2D==2',
                      help='If set to Yes, all MPI slaves will read '
                           'their own images from disc. Otherwise, only '
                           'the master will read images and send them '
                           'through the network to the slaves. Parallel '
                           'file systems like gluster of fhgfs are good '
                           'at parallel disc I/O. NFS may break with many '
                           'slaves reading in parallel.')
        form.addParam('pooledParticles', IntParam, default=3,
                      label='Number of pooled particles:',
                      condition='Class2D==2',
                      help='Particles are processed in individual batches '
                           'by MPI slaves. During each batch, a stack of '
                           'particle images is only opened and closed '
                           'once to improve disk access times. All '
                           'particle images of a single batch are read '
                           'into memory together. The size of these '
                           'batches is at least one particle per thread '
                           'used. The nr_pooled_particles parameter '
                           'controls how many particles are read together '
                           'for each thread. If it is set to 3 and one '
                           'uses 8 threads, batches of 3x8=24 particles '
                           'will be read together. This may improve '
                           'performance on systems where disk access, and '
                           'particularly metadata handling of disk '
                           'access, is a problem. It has a modest cost of '
                           'increased RAM usage.')
        form.addSection(label='CTF')
        form.addParam('continueMsg', LabelParam, default=True,

                      condition='Class2D==2',
                      label='CTF parameters are not available in continue mode')
        form.addParam('doCTF', BooleanParam, default=True,
                      label='Do CTF-correction?', condition='Class2D==2',
                      help='If set to Yes, CTFs will be corrected inside the '
                           'MAP refinement. The resulting algorithm '
                           'intrinsically implements the optimal linear, or '
                           'Wiener filter. Note that input particles should '
                           'contains CTF parameters.')
        form.addParam('hasReferenceCTFCorrected', BooleanParam, default=False,
                      condition='Class2D==2',
                      label='Has reference been CTF-corrected?',
                      help='Set this option to Yes if the reference map '
                           'represents CTF-unaffected density, e.g. it was '
                           'created using Wiener filtering inside RELION or '
                           'from a PDB. If set to No, then in the first '
                           'iteration, the Fourier transforms of the reference '
                           'projections are not multiplied by the CTFs.')

        form.addParam('haveDataBeenPhaseFlipped', LabelParam,

                      condition='Class2D==2',
                      label='Have data been phase-flipped?      '
                            '(Don\'t answer, see help)',
                      help='The phase-flip status is recorded and managed by '
                           'Scipion. \n In other words, when you import or '
                           'extract particles, \nScipion will record whether '
                           'or not phase flipping has been done.\n\n'
                           'Note that CTF-phase flipping is NOT a necessary '
                           'pre-processing step \nfor MAP-refinement in '
                           'RELION, as this can be done inside the internal\n'
                           'CTF-correction. However, if the phases have been '
                           'flipped, the program will handle it.')
        form.addParam('ignoreCTFUntilFirstPeak', BooleanParam, default=False,
                      expertLevel=LEVEL_ADVANCED,
                      label='Ignore CTFs until first peak?',

                      condition='Class2D==2',
                      help='If set to Yes, then CTF-amplitude correction will '
                           'only be performed from the first peak '
                           'of each CTF onward. This can be useful if the CTF '
                           'model is inadequate at the lowest resolution. '
                           'Still, in general using higher amplitude contrast '
                           'on the CTFs (e.g. 10-20%) often yields better '
                           'results. Therefore, this option is not generally '
                           'recommended.')
        form.addParam('doCtfManualGroups', BooleanParam, default=False,
                      label='Do manual grouping ctfs?',

                      condition='Class2D==2',
                      help='Set this to Yes the CTFs will grouping manually.')
        form.addParam('defocusRange', FloatParam, default=1000,
                      label='defocus range for group creation (in Angstroms)',

                      condition='Class2D==2 and doCtfManualGroups',
                      help='Particles will be grouped by defocus.'
                           'This parameter is the bin for an histogram.'
                           'All particles assigned to a bin form a group')
        form.addParam('numParticles', FloatParam, default=10,
                      label='minimum size for defocus group',

                      condition='Class2D==2 and doCtfManualGroups',
                      help='If defocus group is smaller than this value, '
                           'it will be expanded until number of particles '
                           'per defocus group is reached')
        form.addSection(label='Clustering')
        groupClass2D.addParam('ClusteringMethod', EnumParam,
                              choices=['Kmeans','AffinityPropagation'], default=3,
                              label="clustering method",
                              display=EnumParam.DISPLAY_COMBO,
                              help='Select a method to cluster the data. \n ')

        
        form.addParallelSection(threads=1, mpi=1)

    def _insertAllSteps(self):
        
        convertId = self._insertFunctionStep('convertInputStep',
                                             self.inputParticles.get().getObjId(), self.inputVolume.get().getObjId(), 
                                             self.targetResolution.get())
        
        self._insertFunctionStep('constructGroupsStep', self.inputParticles.get().getObjId(),
                                 self.angularSampling.get(), self.angularDistance.get(), self.symmetryGroup.get())
        


        self._insertFunctionStep('classify2DStep')
        self._insertFunctionStep('randomSelectionStep')
        
        self._insertFunctionStep('reconstruct3DStep')
        self._insertFunctionStep('pcaStep')

        #deps = [] # store volumes steps id to use as dependencies for last step
        
        #consGS = self._insertFunctionStep('constructGroupsStep', self.inputParticles.get().getObjId(),
                                 
        #commonParams    = self._getCommonParams()
        #deps.append(convertId)
        
    def convertInputStep(self, particlesId, volId, targetResolution):
        #XmippProtDirectionalClasses.convertInputStep(self, particlesId, volId, targetResolution)
        """ 
        Write the input images as a Xmipp metadata file. 
        particlesId: is only need to detect changes in
        input particles and cause restart from here.
        """
        convXmp.writeSetOfParticles(self.inputParticles.get(), self._getPath('input_particles.xmd'))
        Xdim = self.inputParticles.get().getDimensions()[0]
        Ts = self.inputParticles.get().getSamplingRate()
        newTs = self.targetResolution.get()*0.4
        newTs = max(Ts,newTs)
        newXdim = Xdim*Ts/newTs
        

        params =  '  -i %s' % self._getPath('input_particles.xmd')
        params +=  '  -o %s' % self._getExtraPath('scaled_particles.stk')
        params +=  '  --save_metadata_stack %s' % self._getExtraPath('scaled_particles.xmd')
        params +=  '  --dim %d' % newXdim
        
        self.runJob('xmipp_image_resize',params)
        from pyworkflow.em.convert import ImageHandler
        img = ImageHandler()
        img.convert(self.inputVolume.get(), self._getExtraPath("volume.vol"))
        Xdim = self.inputVolume.get().getDim()[0]
        if Xdim!=newXdim:
            self.runJob("xmipp_image_resize","-i %s --dim %d"%\
                        (self._getExtraPath("volume.vol"),
                        newXdim), numberOfMpi=1)

    def constructGroupsStep(self, particlesId, angularSampling, angularDistance, symmetryGroup):
       ProtDirectionalPruning.constructGroupsStep(self, particlesId, angularSampling, angularDistance, symmetryGroup)
        
    def classify2DStep(self):
        mdClassesParticles = xmippLib.MetaData()
        fnClassParticles = self._getPath('input_particles.xmd')
        mdClassesParticles.read(fnClassParticles)
        fnNeighbours = self._getExtraPath("neighbours.xmd")
        fnGallery = self._getExtraPath("gallery.stk")
        nop = self.noOfParticles.get()
        fnDirectional = self._getPath("directionalClasses.xmd")
        mdOut = xmippLib.MetaData()
        mdRef = xmippLib.MetaData(self._getExtraPath("gallery.doc"))


        for block in xmippLib.getBlocksInMetaDataFile(fnNeighbours):
            imgNo = block.split("_")[1]
            galleryImgNo = int(block.split("_")[1])


            fnDir = self._getExtraPath("direction_%s" % imgNo)
            rot = mdRef.getValue(xmippLib.MDL_ANGLE_ROT,galleryImgNo)
            tilt = mdRef.getValue(xmippLib.MDL_ANGLE_TILT,galleryImgNo )
            psi = 0.0

            if not exists(fnDir):
                makePath(fnDir)

            if self.Class2D.get() == self.CL2D:
                Nlevels = int(math.ceil(math.log(self.directionalClasses.get())
                                        / math.log(2)))
                fnOut = join(fnDir, "level_%02d/class_classes.stk" % Nlevels)
                if not exists(fnOut):
                    fnBlock = "%s@%s" % (block, fnNeighbours)
                    if getSize(fnBlock) > nop:
                        totset = getSize(fnBlock)
                        finset = int(totset / nop)+1

                        args = "-i %s --odir %s --ref0 %s@%s --iter %d " \
                                   "--nref %d --distance correlation " \
                                   "--classicalMultiref --maxShift %d" % \
                                   (fnBlock, fnDir, imgNo, fnGallery,
                                    self.CL2D_it.get(),
                                    finset,
                                    self.CL2D_shift.get())
                        self.runJob("xmipp_classify_CL2D", args)
                        fnAlignRoot = join(fnDir, "classes")
                        fnOut = join(fnDir, "level_%02d/class_classes.stk" % (
                                    finset - 1))

                        for n in range(finset):
                            objId = mdOut.addObject()
                            mdOut.setValue(xmippLib.MDL_REF,int(imgNo), objId)
                            mdOut.setValue(xmippLib.MDL_IMAGE,
                                           "%d@%s" % (n + 1, fnOut), objId)
                            mdOut.setValue(xmippLib.MDL_IMAGE_IDX, long(n + 1),
                                           objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_ROT, rot, objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_TILT, tilt, objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_PSI, psi, objId)
                            mdOut.setValue(xmippLib.MDL_SHIFT_X, 0.0, objId)
                            mdOut.setValue(xmippLib.MDL_SHIFT_Y, 0.0, objId)
                            mdOut.write("%s@%s" % (block, fnDirectional),
                                        xmippLib.MD_APPEND)
                        mdOut.clear()



            elif self.Class2D.get() == self.ML2D:
                fnOut = join(fnDir, "class_")
                fnBlock = "%s@%s" % (block, fnNeighbours)

                if getSize(fnBlock) > nop:
                        totset = getSize(fnBlock)
                        finset = int(totset / nop)+1


                        params = "-i %s --oroot %s --nref %d --fast --mirror --iter %d" \
                                 % (fnBlock,
                                    fnOut,
                                    finset,
                                    self.maxIters.get())

                        self.runJob("xmipp_ml_align2d", params)
                        fnOut = self._getExtraPath(
                            "direction_%s/class_classes.stk" % imgNo)
                        for n in range(finset):
                            objId = mdOut.addObject()
                            mdOut.setValue(xmippLib.MDL_REF,int(imgNo), objId)
                            mdOut.setValue(xmippLib.MDL_IMAGE,
                                           "%d@%s" % (n + 1, fnOut), objId)
                            mdOut.setValue(xmippLib.MDL_IMAGE_IDX, long(n + 1),
                                           objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_ROT, rot, objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_TILT, tilt, objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_PSI, psi, objId)
                            mdOut.setValue(xmippLib.MDL_SHIFT_X, 0.0, objId)
                            mdOut.setValue(xmippLib.MDL_SHIFT_Y, 0.0, objId)
                            mdOut.write("%s@%s" % (block, fnDirectional),
                                        xmippLib.MD_APPEND)
                        mdOut.clear()

            else:

                relPart = self._createSetOfParticles()
                relPart.copyInfo(self.inputParticles.get())
                fnRelion = self._getExtraPath('relion_%s.star' % imgNo)
                fnBlock = "%s@%s" % (block, fnNeighbours)
                fnRef = "%s@%s" % (imgNo, fnGallery)
                if getSize > nop:
                        totset = getSize(fnBlock)
                        finset = int(totset / 100) +1
                        print(finset)
                        convXmp.readSetOfParticles(fnBlock, relPart)

                        if self.copyAlignment.get():
                            alignType = relPart.getAlignment()
                            alignType != em.ALIGN_NONE
                        else:
                            alignType = em.ALIGN_NONE

                        alignToPrior = getattr(self, 'alignmentAsPriors',
                                               True)
                        fillRandomSubset = getattr(self, 'fillRandomSubset',
                                                   False)

                        writeSetOfParticles(relPart, fnRelion,
                                            self._getExtraPath(),
                                            alignType=alignType,
                                            postprocessImageRow=self._postprocessParticleRow,
                                            fillRandomSubset=fillRandomSubset)

                        if alignToPrior:
                            mdParts = md.MetaData(fnRelion)
                            self._copyAlignAsPriors(mdParts, alignType)
                            mdParts.write(fnRelion)
                        if self.doCtfManualGroups:
                            self._splitInCTFGroups(fnRelion)

                        fnOut = join(fnDir, "class")
                        print("SAAAA", fnOut)
                        args = {}
                        self._setNormalArgs(args)
                        args['--i'] = fnRelion
                        args['--o'] = fnOut
                        args['--K'] = finset
                        if self.referenceClassification.get():
                            args['--ref'] = fnRef
                        self._setComputeArgs(args)

                        params = ' '.join(['%s %s' % (k, str(v)) for k, v in
                                           args.iteritems()])

                        self.runJob(self._getRelionProgram(), params)
                        it = self.numberOfIterations.get()
                        if it < 10:
                            model = '_it00%d_' % it
                        else:
                            model = '_it0%d_' % it

                        fnModel = (fnOut + model + 'classes.mrcs')
                        for n in range(finset):
                            objId = mdOut.addObject()
                            print(objId)
                            mdOut.setValue(xmippLib.MDL_REF, int(imgNo), objId)
                            mdOut.setValue(xmippLib.MDL_IMAGE,
                                           "%d@%s" % (n + 1, fnModel), objId)
                            mdOut.setValue(xmippLib.MDL_IMAGE_IDX, long(n + 1),
                                           objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_ROT, rot, objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_TILT, tilt, objId)
                            mdOut.setValue(xmippLib.MDL_ANGLE_PSI, psi, objId)
                            mdOut.setValue(xmippLib.MDL_SHIFT_X, 0.0, objId)
                            mdOut.setValue(xmippLib.MDL_SHIFT_Y, 0.0, objId)

                            mdOut.write("%s@%s" % (block, fnDirectional),
                                        xmippLib.MD_APPEND)
                        mdOut.clear()



    def randomSelectionStep(self):
        mdRandom=xmippLib.MetaData()
        mdClass=xmippLib.MetaData()
        mdRef = xmippLib.MetaData(self._getExtraPath("gallery.doc"))
        fnDirectional = self._getPath("directionalClasses.xmd")


        for i in range (self.randomIteration):
            stack=i+1
            fnRandomAverages = self._getExtraPath('randomAverages_%s' %stack)
            #nop = self.noOfParticles.get()
            for indx, block in enumerate(
                    xmippLib.getBlocksInMetaDataFile(fnDirectional)[:]):

                fnClasses = "%s@%s" % (block, fnDirectional)
                mdClass.read(fnClasses)
                #numClass= self.directionalClasses.get()
                totset = getSize(fnClasses)
                finset = int(totset / 100) + 1
                if finset > 1:
                   rc = random.randint(1, finset)
                else:
                   rc = 1


                imgNo = block.split("_")[1]
                galleryImgNo = int(block.split("_")[1])
                rot = mdRef.getValue(xmippLib.MDL_ANGLE_ROT, galleryImgNo)
                tilt = mdRef.getValue(xmippLib.MDL_ANGLE_TILT, galleryImgNo)
                psi = 0.0
                objId = mdRandom.addObject()
                mdRandom.setValue(xmippLib.MDL_IMAGE,
                            mdClass.getValue(xmippLib.MDL_IMAGE, rc),
                            objId)
                mdRandom.setValue(xmippLib.MDL_REF, int(imgNo), objId)
                mdRandom.setValue(xmippLib.MDL_ANGLE_ROT, rot, objId)
                mdRandom.setValue(xmippLib.MDL_ANGLE_TILT, tilt, objId)
                mdRandom.setValue(xmippLib.MDL_ANGLE_PSI, psi, objId)
                mdRandom.setValue(xmippLib.MDL_SHIFT_X, 0.0, objId)
                mdRandom.setValue(xmippLib.MDL_SHIFT_Y, 0.0, objId)

            mdRandom.write(fnRandomAverages+'.xmd')
            mdRandom.clear()
            print("Direction in %s and class in %s" %(imgNo,rc))




    def reconstruct3DStep(self):

        self.Xdim = self.inputParticles.get().getDimensions()[0]
        ts = self.inputParticles.get().getSamplingRate()
        maxFreq=self.targetResolution.get()
        normFreq = 0.25 * (maxFreq / ts)
        K = 0.25 * (maxFreq / ts)
        if K < 1:
            K = 1
        self.Xdim2 = self.Xdim / K
        if self.Xdim2 < 32:
            self.Xdim2 = 32
            K = self.Xdim / self.Xdim2

        freq = ts / maxFreq
        ts = K * ts
        Mc = (self.backRadius.get()) * (self.Xdim2/2)



        for i in range (self.randomIteration):
            stack=i+1
            fnRandomAverages = self._getExtraPath('randomAverages_%s' %stack)
            self.runJob("xmipp_reconstruct_fourier","-i %s.xmd -o %s.vol --sym %s --max_resolution %f" %(fnRandomAverages,fnRandomAverages,self.symmetryGroup.get(),normFreq))
            self.runJob("xmipp_transform_filter",   "-i %s.vol -o %s.vol --fourier low_pass %f --bad_pixels outliers 0.5" %(fnRandomAverages,fnRandomAverages,freq))
            self.runJob("xmipp_transform_mask","-i %s.vol  -o %s.vol --mask circular %f" %(fnRandomAverages,fnRandomAverages,Mc))


    def pcaStep(self):

        ##"".vol to .mrc conversion""##

        listVol = []
        Plugin.setEnviron()
        for i in range (self.randomIteration):
            stack=i+1
            fnRandomAverages = self._getExtraPath('randomAverages_%s' %stack)
            inputVol = fnRandomAverages +'.vol'
            img = ImageHandler()
            img.convert(inputVol, self._getExtraPath("volume_%s.mrc" %stack))
            MrcFile = self._getExtraPath("volume_%s.mrc" %stack)
            listVol.append(MrcFile)
        # ""AVERAGE VOLUME GENERATION""#
        listVol = self._getPathMaps() if not bool(listVol) else listVol


        try:
           avgVol = self._getFileName('avgMap', lev=self._level)
        except:
            avgVol = self._getPath('map_average.mrc')

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

        ##""PCA ESTIMATION""##
        npVol = loadMrc(listVol.__getitem__(0), False)
        dim = npVol.shape[0]
        lenght = dim ** 3
        cov_matrix = []

        for vol in listVol:
            npVol = loadMrc(vol, False)
            volList = npVol.reshape(lenght)

            row = []
            b = volList - npAvgVol.reshape(lenght)
            print (b, 'b')
            for j in listVol:
                npVol = loadMrc(j, writable=False)
                volList = npVol.reshape(lenght)
                volList_two = volList - npAvgVol.reshape(lenght)
                print (volList, "vollist")
                temp_a = np.corrcoef(volList_two, b).item(1)
                print (temp_a, "temp_a")
                row.append(temp_a)
            cov_matrix.append(row)
            print("Doing PCA now now now")


        ##""DO PCA""##

        u, s, vh = np.linalg.svd(cov_matrix)
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

        eigValsFile = 'eigenvalues.txt'
        self._createMFile(s, eigValsFile)

        eigVecsFile = 'eigenvectors.txt'
        self._createMFile(vh, eigVecsFile)

        vhDel = np.transpose(np.delete(vh, np.s_[sCut:vh.shape[1]], axis=0))
        self._createMFile(vhDel, 'matrix_vhDel.txt')



        ###""MATCH PROJECTION"""####

        mat_one = []
        for vol in listVol:
            volNp = loadMrc(vol, False)
            volList = volNp.reshape(lenght)
            print (volList, "volList")
            row_one = []
            for j in listVol:
                npVol = loadMrc(j, writable=False)
                volList_three = npVol.reshape(lenght)
                j_trans = volList_three.transpose()
                matrix_two = np.dot(volList, j_trans)
                row_one.append(matrix_two)
            mat_one.append(row_one)

        matProj = np.dot(mat_one, vhDel)
        print (matProj, "matProj")

        ##""Construct PCA histogram""##
        x_proj = [item[0] for item in matProj]
        y_proj = [item[1] for item in matProj]
        print (x_proj, "x_proj")
        print (y_proj, "y_proj")
        print (len(x_proj), "xlength")
        print (len(y_proj), "ylength")

        ## save coordinates:
        mat_file = 'matProj_splic.txt'
        self._createMFile(matProj, mat_file)
        x_file = 'x_proj_splic.txt'
        self._createMFile(x_proj, x_file)
        y_file = 'y_proj_splic.txt'
        self._createMFile(y_proj, y_file)

        ##Kmeans&AffinityPropagation

        if self.ClusteringMethod.get() == 3:
            from sklearn.cluster import KMeans
            print('projections: ', matProj.shape[1])
            kmeans = KMeans(n_clusters=matProj.shape[1]).fit(matProj)
            op = kmeans.labels_
            print(op)

        elif self.ClusteringMethod.get() == 4:
            from sklearn.cluster import AffinityPropagation
            ap = AffinityPropagation(damping=0.9).fit(matProj)
            print("cluster_centers", ap.cluster_centers_)
            op= ap.labels_
            print(op)






    def createOutputStep(self):
        pass
        #partSet = self.inputParticles.get()
        #classes3D = self._createSetOfClasses3D(partSet)
        #self._fillClassesFromIter(classes3D, self._lastIter())

        #self._defineOutputs(outputClasses=classes3D)
        #self._defineSourceRelation(self.inputParticles, classes3D)

        ## create a SetOfVolumes and define its relations
        #volumes = self._createSetOfVolumes()
        #volumes = self._createSetOfVolumes()
        #self._fillVolSetFromIter(volumes, self._lastIter())
        #volumes.setSamplingRate(partSet.getSamplingRate())

        #for class3D in classes3D:
         #   vol = class3D.getRepresentative()
          #  vol.setObjId(class3D.getObjId())
           # volumes.append(vol)

        #self._defineOutputs(outputVolumes=volumes)
        #self._defineSourceRelation(self.inputParticles, volumes)
    #--------------------------- INFO functions -------------------------------------------- 
    def _validate(self):
        pass
    
    def _summary(self):
        pass
    
    def _methods(self):
        messages = []
        return messages
    
    def _citations(self):
        return ['Vargas2014a']
    
    #--------------------------- UTILS functions -------------------------------------------- 
    #def _updateLocation(self, item, row):

     #   index, filename = xmippToLocation(row.getValue(md.MDL_IMAGE))
      #  item.setLocation(index, filename)
    def _setNormalArgs(self, args):
        maskDiameter = self.maskDiameterA.get()
        newTs = self.targetResolution.get() * 0.4
        if maskDiameter <= 0:
          x = self._getInputParticles().getDim()[0]
          maskDiameter = self._getInputParticles().getSamplingRate() * x

          args.update({'--particle_diameter': maskDiameter,
                     '--angpix': newTs,
                     })

        args['--zero_mask'] = ''


        self._setCTFArgs(args)
        self._setBasicArgs(args)

    def _setComputeArgs(self, args):
        if not self.combineItersDisc:
            args['--dont_combine_weights_via_disc'] = ''

        if not self.useParallelDisk:
            args['--no_parallel_disc_io'] = ''

        if self.allParticlesRam:
            args['--preread_images'] = ''
        else:
             if self.scratchDir.get():
                args['--scratch_dir'] = self.scratchDir.get()

        args['--pool'] = self.pooledParticles.get()

        if self.doGpu:
            args['--gpu'] = self.gpusToUse.get()

        args['--j'] = self.numberOfThreads.get()

    def _setBasicArgs(self, args):
        """ Return a dictionary with basic arguments. """
        args.update({'--flatten_solvent': '',
                     '--dont_check_norm': '',
                     '--scale': '',
                     '--oversampling': 1
                     })

       # if self.IS_CLASSIFY:
        args['--tau2_fudge'] = self.regularisationParamT.get() #This param should be set by user
        args['--iter'] = self.numberOfIterations.get()

        self._setSamplingArgs(args)

    def _setCTFArgs(self, args):
        if self.doCTF.get():
           args['--ctf'] = ''

        if self._getInputParticles().isPhaseFlipped():
            args['--ctf_phase_flipped'] = ''

        if self.ignoreCTFUntilFirstPeak.get():
            args['--ctf_intact_first_peak'] = ''

    def _getRelionProgram(self, program='relion_refine'):
        #""" Get the program name depending on the MPI use or not. ""
        if self.numberOfMpi > 1:
             program += '_mpi'
        return program

    def _getInputParticles(self):
        return self.inputParticles.get()

    def _setSamplingArgs(self, args):
        """ Set sampling related params. """
        # Sampling stuff
        if self.doImageAlignment:
            args['--offset_range'] = self.offsetSearchRangePix.get()
            args['--offset_step']  = self.offsetSearchStepPix.get() * 2
            args['--psi_step'] = self.inplaneAngularSamplingDeg.get() * 2


    def _copyAlignAsPriors(self, mdParts, alignType):
        # set priors equal to orig. values
        mdParts.copyColumn(md.RLN_ORIENT_ORIGIN_X_PRIOR, md.RLN_ORIENT_ORIGIN_X)
        mdParts.copyColumn(md.RLN_ORIENT_ORIGIN_Y_PRIOR, md.RLN_ORIENT_ORIGIN_Y)
        mdParts.copyColumn(md.RLN_ORIENT_PSI_PRIOR, md.RLN_ORIENT_PSI)

        if alignType == em.ALIGN_PROJ:
            mdParts.copyColumn(md.RLN_ORIENT_ROT_PRIOR, md.RLN_ORIENT_ROT)
            mdParts.copyColumn(md.RLN_ORIENT_TILT_PRIOR, md.RLN_ORIENT_TILT)


    def _postprocessParticleRow(self, part, partRow):
        if part.hasAttribute('_rlnGroupName'):
            partRow.setValue(md.RLN_MLMODEL_GROUP_NAME,
                             '%s' % part.getAttributeValue('_rlnGroupName'))
        else:
            partRow.setValue(md.RLN_MLMODEL_GROUP_NAME,
                             '%s' % part.getMicId())

        ctf = part.getCTF()

        if ctf is not None and ctf.getPhaseShift():
            partRow.setValue(md.RLN_CTF_PHASESHIFT, ctf.getPhaseShift())

    def _splitInCTFGroups(self, fnRelion):
        """ Add a new column in the image star to separate the particles
        into ctf groups """

        splitInCTFGroups(fnRelion,
                         self.defocusRange.get(),
                         self.numParticles.get())

    def _getIterVolumes(self, it, clean=False):
        """ Return a volumes .sqlite file for this iteration.
        If the file doesn't exists, it will be created by
        converting from this iteration data.star file.
        """
        sqlteVols = self._getFileName('volumes_scipion', iter=it)

        if clean:
            cleanPath(sqlteVols)

        if not exists(sqlteVols):
            volSet = self.OUTPUT_TYPE(filename=sqlteVols)
            self._fillVolSetFromIter(volSet, it)
            volSet.write()
            volSet.close()
        return sqlteVols

    def _fillVolSetFromIter(self, volSet, it):
        volSet.setSamplingRate(self._getInputParticles().getSamplingRate())
        modelStar = md.MetaData('model_classes@' +
                                self._getFileName('model', iter=it))
        for row in md.iterRows(modelStar):
            fn = row.getValue('rlnReferenceImage')
            fnMrc = fn + ":mrc"
            itemId = self._getClassId(fn)
            classDistrib = row.getValue('rlnClassDistribution')
            accurracyRot = row.getValue('rlnAccuracyRotations')
            accurracyTras = row.getValue('rlnAccuracyTranslations')
            resol = row.getValue('rlnEstimatedResolution')

            if classDistrib > 0:
                vol = em.Volume()
                self._invertScaleVol(fnMrc)
                vol.setFileName(self._getOutputVolFn(fnMrc))
                vol.setObjId(itemId)
                vol._rlnClassDistribution = em.Float(classDistrib)
                vol._rlnAccuracyRotations = em.Float(accurracyRot)
                vol._rlnAccuracyTranslations = em.Float(accurracyTras)
                vol._rlnEstimatedResolution = em.Float(resol)
                volSet.append(vol)


    def _fillClassesFromIter(self, clsSet, iteration):
        """ Create the SetOfClasses3D from a given iteration. """
        self._loadClassesInfo(iteration)
        dataStar = self._getFileName('data', iter=iteration)
        clsSet.classifyItems(updateItemCallback=self._updateParticle,
                             updateClassCallback=self._updateClass,
                             itemDataIterator=md.iterRows(dataStar,
                                                          sortByLabel=md.RLN_IMAGE_ID))

    def _updateParticle(self, item, row):
        item.setClassId(row.getValue(md.RLN_PARTICLE_CLASS))
        item.setTransform(rowToAlignment(row, em.ALIGN_PROJ))

        item._rlnLogLikeliContribution = em.Float(
            row.getValue('rlnLogLikeliContribution'))
        item._rlnMaxValueProbDistribution = em.Float(
            row.getValue('rlnMaxValueProbDistribution'))
        item._rlnGroupName = em.String(row.getValue('rlnGroupName'))

    def _updateClass(self, item):
        classId = item.getObjId()
        if classId in self._classesInfo:
            index, fn, row = self._classesInfo[classId]
            fn += ":mrc"
            item.setAlignmentProj()
            item.getRepresentative().setLocation(index, fn)
            item._rlnclassDistribution = em.Float(
                row.getValue('rlnClassDistribution'))
            item._rlnAccuracyRotations = em.Float(
                row.getValue('rlnAccuracyRotations'))
            item._rlnAccuracyTranslations = em.Float(
                row.getValue('rlnAccuracyTranslations'))

    def _createMFile(self, matrix, name='matrix.txt'):
        print (name, "name")
        f = open(name, 'w')
        for list in matrix:
            s = "%s\n" % list
            f.write(s)
        f.close()

    def _clusteringData(self, matProj):
        method = self.ClusteringMethod.get()
        if method == 3:
            return self._doSklearnKmeans(matProj)
        else:
            return self._doSklearnAffProp(matProj)

    def _doSklearnKmeans(self, matProj):
        from sklearn.cluster import KMeans
        print('projections: ', matProj.shape[1])
        kmeans = KMeans(n_clusters=matProj.shape[1]).fit(matProj)
        return kmeans.labels_

    def _doSklearnAffProp(self, matProj):
        from sklearn.cluster import AffinityPropagation
        ap = AffinityPropagation(damping=0.9).fit(matProj)
        print("cluster_centers", ap.cluster_centers_)
        return ap.labels_

    def _mrcToNp(self, volList):
        listNpVol = []
        for vol in volList:
            volNp = loadMrc(vol, False)
            dim = volNp.shape[0]
            lenght = dim**3
            volList = volNp.reshape(lenght)
            listNpVol.append(volList)
        return listNpVol, listNpVol[0].dtype




    #fig = plt.figure()
    #ax = fig.add_subplot(1,1,1)
    #plt.hexbin(x_proj, y_proj, gridsize=20, mincnt=1, bins='log')
    #plt.xlabel('x_pca', fontsize=16)
    #plt.ylabel('y_pca', fontsize=16)
    #plt.colorbar()
    #plt.savefig('interpolated_controlPCA_splic.png', dpi=100)
    #plt.close(fig)