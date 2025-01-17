# **************************************************************************
# *
# * Authors:     Josue Gomez Blanco (josue.gomez-blanco@mcgill.ca)
# *              Javier Vargas Balbuena (javier.vargasbalbuena@mcgill.ca)
# *
# * Department of Anatomy and Cell Biology, McGill University
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
# *  e-mail address 'scipion@cnb.csic.es'
# *
# **************************************************************************
from glob import glob
import numpy as np
from pwem.emlib.image import ImageHandler
from scipy import stats

from pwem.protocols import EMProtocol
from pwem.objects import SetOfVolumes, Volume, Float, ALIGN_PROJ
import pwem.emlib.metadata as md
import pyworkflow.protocol.params as params
from pyworkflow.protocol import LEVEL_ADVANCED
import pyworkflow.utils.path as pwpath
from pyworkflow.utils.path import replaceBaseExt, replaceExt

from cryomethods.constants import (METHOD, ANGULAR_SAMPLING_LIST,
                                   MASK_FILL_ZERO)
import cryomethods.convert.convert as conv
from cryomethods import Plugin


class ProtocolBase(EMProtocol):
    """ This class contains the common functions for protocols developed by
    cryomethods that uses Relion programs.
    """
    IS_2D = False
    IS_VOLSELECTOR = False
    IS_AUTOCLASSIFY = False
    OUTPUT_TYPE = SetOfVolumes
    FILE_KEYS = ['data', 'optimiser', 'sampling']
    PREFIXES = ['']


    def __init__(self, **args):
        EMProtocol.__init__(self, **args)

    def _initialize(self):
        """ This function is mean to be called after the
        working dir for the protocol have been set.
        (maybe after recovery from mapper)
        """
        self._createFilenameTemplates()
        self._createTemplates()
        self._createVolDict()

    def _createTemplates(self):
        """ Setup the regex on how to find iterations. Suold be implemented
        in subclasses"""
        pass

    def _createVolDict(self):
        self.volDict = {}
        for i, vol in enumerate(self.inputVolumes.get()):
            self.volDict[i+1] = vol.getObjId()

    # -------------------------- DEFINE param functions -----------------------
    def _defineConstants(self):
        self.IS_3D = not self.IS_2D

    def _defineInputParams(self, form):
        self._defineConstants()
        form.addSection(label='Input')
        form.addParam('inputParticles', params.PointerParam,
                      pointerClass='SetOfParticles',
                      important=True,
                      label="Input particles",
                      help='Select the input images from the project.')
        form.addParam('maskDiameterA', params.IntParam, default=-1,
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
        form.addParam('maskZero', params.EnumParam, default=0,
                      choices=['Yes, fill with zeros',
                               'No, fill with random noise'],
                      label='Mask particles with zeros?',
                      help='If set to <Yes>, then in the individual particles, '
                           'the area outside a circle with the radius '
                           'of the particle will be set to zeros prior to '
                           'taking the Fourier transform. '
                           'This will remove noise and therefore increase '
                           'sensitivity in the alignment and classification. '
                           'However, it will also introduce correlations '
                           'between the Fourier components that are not '
                           'modelled. When set to <No>, then the solvent area '
                           'is filled with random noise, which prevents '
                           'introducing correlations.High-resolution '
                           'refinements (e.g. in 3D auto-refine) tend to work '
                           'better when filling the solvent area with random '
                           'noise, some classifications go better when using '
                           'zeros.')
        form.addParam('copyAlignment', params.BooleanParam, default=False,
                      label='Consider previous alignment?',
                      help='If set to Yes, then alignment information from'
                           ' input particles will be considered.')
        form.addParam('alignmentAsPriors', params.BooleanParam,
                      default=False,
                      condition='copyAlignment',
                      expertLevel=LEVEL_ADVANCED,
                      label='Consider alignment as priors?',
                      help='If set to Yes, then alignment information from '
                           'input particles will be considered as PRIORS. '
                           'This option is mandatory if you want to do '
                           'local searches')
        form.addParam('fillRandomSubset', params.BooleanParam,
                      default=False, condition='copyAlignment',
                      expertLevel=LEVEL_ADVANCED,
                      label='Consider random subset value?',
                      help='If set to Yes, then random subset value '
                           'of input particles will be put into the'
                           'star file that is generated.')

        if self.IS_2D:
            form.addParam('referenceAverages', params.PointerParam,
                          pointerClass='SetOfAverages', allowsNull=True,
                          expertLevel=LEVEL_ADVANCED,
                          label='Reference averages',
                          help='This option is not recommended and should be '
                               'used with care. The provided averages will be '
                               'used as initial 2D references. If this option '
                               'is used, the number of classes will be '
                               'ignored.')
        if self.IS_VOLSELECTOR:
            group = form.addGroup('Volume Selector')

            group.addParam('subsetSize', params.IntParam, default=1000,
                           label='Subset size',
                           help='Number of individual particles that will be '
                                'use to obtain the best initial volume')
            group.addParam('targetResol', params.FloatParam, default=10,
                           label='Target Resolution (A)',
                           help='In order to save time, you could rescale both '
                                'particles and maps to a pisel size = resol/2. '
                                'If set to 0, no rescale will be applied to '
                                'the initial references.')
            group.addParam('changeMaps', params.BooleanParam,
                           default=False,
                           label='change initial maps every 5 iterations?',
                           help='')

        elif self.IS_AUTOCLASSIFY:
            group = form.addGroup('Auto classify')

            group.addParam('minPartsToStop', params.FloatParam, default=5000,
                           label='min particles to stop',
                           help='Minimum number of particles per class that is '
                                'needed to do another classification step')
            group.addParam('numberOfClasses', params.IntParam, default=2,
                           label='Number of classes:',
                           help='The number of classes (K) for a '
                                'multi-reference refinement. These classes '
                                'will be made in an unsupervised manner from '
                                'a single reference by division of the data '
                                'into random subsets during the first '
                                'iteration.')
            if not self.IS_2D:
                group.addParam('useReslog', params.BooleanParam,
                               default=True,
                               label='Use reslog as stop condition?:',
                               help='')
                group.addParam('doGrouping', params.BooleanParam,
                               default=True,
                               label='Grouping the classes:',
                               help='')
                group.addParam('classMethod', params.EnumParam, default=1,
                               choices=METHOD, condition='doGrouping',
                               label='Method to determine the classes:',
                               help='')
            else:
                group.addHidden('useReslog', params.BooleanParam,
                               default=False)
                group.addHidden('doGrouping', params.BooleanParam,
                               default=False)

    def _defineReferenceParams(self, form, expertLev=LEVEL_ADVANCED):
        form.addSection('Reference 3D map')
        referenceClass = 'SetOfVolumes'
        referenceLabel = 'Input volumes'

        if not self.IS_VOLSELECTOR:
            referenceClass += ', Volume'
            referenceLabel = 'Input volume(s)'

        form.addParam('inputVolumes', params.PointerParam,
                      pointerClass=referenceClass,
                      important=True,
                      label=referenceLabel,
                      help='Initial reference 3D map(s)')
        if self.IS_VOLSELECTOR:
            form.addParam('numOfVols', params.IntParam,
                          default=5,  label='Number of Volumes',
                          help='Select Volumes to work with.')
        form.addParam('referenceMask', params.PointerParam,
                      pointerClass='VolumeMask', expertLevel=expertLev,
                      label='Reference mask (optional)', allowsNull=True,
                      help='A volume mask containing a (soft) mask with '
                           'the same dimensions as the reference(s), '
                           'and values between 0 and 1, with 1 being 100% '
                           'protein and 0 being 100% solvent. The '
                           'reconstructed reference map will be multiplied '
                           'by this mask. If no mask is given, a soft '
                           'spherical mask based on the <radius> of the '
                           'mask for the experimental images will be '
                           'applied.\n\n'
                           'In some cases, for example for non-empty '
                           'icosahedral viruses, it is also useful to use '
                           'a second mask. Check _Advaced_ level and '
                           'select another volume mask')
        form.addParam('solventMask', params.PointerParam,
                      pointerClass='VolumeMask',
                      expertLevel=LEVEL_ADVANCED, allowsNull=True,
                      label='Second reference mask (optional)',
                      help='For all white (value 1) pixels in this second '
                           'mask the corresponding pixels in the '
                           'reconstructed map are set to the average value '
                           'of these pixels. Thereby, for example, the '
                           'higher density inside the virion may be set to '
                           'a constant. Note that this second mask should '
                           'have one-values inside the virion and '
                           'zero-values in the capsid and the solvent '
                           'areas.')
        form.addParam('solventFscMask', params.BooleanParam, default=False,
                      expertLevel=LEVEL_ADVANCED,
                      label='Use solvent-flattened FSCs?',
                      help='If set to Yes, then instead of using '
                           'unmasked maps to calculate the gold-standard '
                           'FSCs during refinement, masked half-maps '
                           'are used and a post-processing-like '
                           'correction of the FSC curves (with '
                           'phase-randomisation) is performed every '
                           'iteration. This only works when a reference '
                           'mask is provided on the I/O tab. This may '
                           'yield higher-resolution maps, especially '
                           'when the mask contains only a relatively '
                           'small volume inside the box.')
        form.addParam('isMapAbsoluteGreyScale', params.BooleanParam,
                      default=False,
                      label="Is initial 3D map on absolute greyscale?",
                      help='The probabilities are based on squared '
                           'differences, so that the absolute grey scale is '
                           'important. \n'
                           'Probabilities are calculated based on a Gaussian '
                           'noise model, which contains a squared difference '
                           'term between the reference and the experimental '
                           'image. This has a consequence that the reference '
                           'needs to be on the same absolute intensity '
                           'grey-scale as the experimental images. RELION and '
                           'XMIPP reconstruct maps at their absolute '
                           'intensity grey-scale. Other packages may perform '
                           'internal normalisations of the reference density, '
                           'which will result in incorrect grey-scales. '
                           'Therefore: if the map was reconstructed in RELION '
                           'or in XMIPP, set this option to Yes, otherwise '
                           'set it to No. If set to No, RELION will use a ('
                           'grey-scale invariant) cross-correlation criterion '
                           'in the first iteration, and prior to the second '
                           'iteration the map will be filtered again using '
                           'the initial low-pass filter. This procedure is '
                           'relatively quick and typically does not '
                           'negatively affect the outcome of the subsequent '
                           'MAP refinement. Therefore, if in doubt it is '
                           'recommended to set this option to No.')
        form.addParam('symmetryGroup', params.StringParam, default='c1',
                      label="Symmetry",
                      help='If the molecule is asymmetric, set Symmetry '
                           'group to C1. Note their are multiple '
                           'possibilities for icosahedral symmetry:\n'
                           '* I1: No-Crowther 222 (standard in Heymann,'
                           'Chagoyen  & Belnap, JSB, 151 (2005) 196-207)\n'
                           '* I2: Crowther 222                          \n'
                           '* I3: 52-setting (as used in SPIDER?)       \n'
                           '* I4: A different 52 setting                \n'
                           'The command *relion_refine --sym D2 '
                           '--print_symmetry_ops* prints a list of all '
                           'symmetry operators for symmetry group D2. RELION '
                           'uses MIPP\'s libraries for symmetry operations. '
                           'Therefore, look at the XMIPP Wiki for more '
                           'details:\n'
                           'http://xmipp.cnb.csic.es/twiki/bin/view/Xmipp'
                           '/WebHome?topic=Symmetry')
        form.addParam('initialLowPassFilterA', params.FloatParam,
                      default=25 if self.IS_VOLSELECTOR else 40,
                      label='Initial low-pass filter (A)',
                      help='It is recommended to strongly low-pass filter '
                           'your initial reference map. If it has not yet '
                           'been low-pass filtered, it may be done '
                           'internally using this option. If set to 0, '
                           'no low-pass filter will be applied to the '
                           'initial reference(s).')

    def _defineCTFParams(self, form, expertLev=LEVEL_ADVANCED):
        form.addSection('CTF')
        form.addParam('doCTF', params.BooleanParam, default=True,
                      expertLevel=expertLev,
                      label='Do CTF-correction?',
                      help='If set to Yes, CTFs will be corrected inside the '
                           'MAP refinement. The resulting algorithm '
                           'intrinsically implements the optimal linear, or '
                           'Wiener filter. Note that input particles should '
                           'contains CTF parameters.')
        form.addParam('hasReferenceCTFCorrected', params.BooleanParam,
                      default=False, expertLevel=expertLev,
                      label='Has reference been CTF-corrected?',
                      help='Set this option to Yes if the reference map '
                           'represents CTF-unaffected density, e.g. it was '
                           'created using Wiener filtering inside RELION or '
                           'from a PDB. If set to No, then in the first '
                           'iteration, the Fourier transforms of the reference '
                           'projections are not multiplied by the CTFs.')
        form.addParam('haveDataBeenPhaseFlipped', params.LabelParam,
                      expertLevel=expertLev,
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
        form.addParam('ignoreCTFUntilFirstPeak', params.BooleanParam,
                      default=False, expertLevel=LEVEL_ADVANCED,
                      label='Ignore CTFs until first peak?',
                      help='If set to Yes, then CTF-amplitude correction will '
                           'only be performed from the first peak '
                           'of each CTF onward. This can be useful if the CTF '
                           'model is inadequate at the lowest resolution. '
                           'Still, in general using higher amplitude contrast '
                           'on the CTFs (e.g. 10-20%) often yields better '
                           'results. Therefore, this option is not generally '
                           'recommended.')
        form.addParam('doCtfManualGroups', params.BooleanParam, default=False,
                      label='Do manual grouping ctfs?', expertLevel=expertLev,
                      help='Set this to Yes the CTFs will grouping manually.')
        form.addParam('defocusRange', params.FloatParam, default=500,
                      label='defocus range for group creation (in Angstroms)',
                      condition='doCtfManualGroups', expertLevel=expertLev,
                      help='Particles will be grouped by defocus.'
                           'This parameter is the bin for an histogram.'
                           'All particles assigned to a bin form a group')
        form.addParam('numParticles', params.FloatParam, default=200,
                      label='minimum size for defocus group',
                      condition='doCtfManualGroups', expertLevel=expertLev,
                      help='If defocus group is smaller than this value, '
                           'it will be expanded until number of particles '
                           'per defocus group is reached')

    def _defineOptimizationParams(self, form, expertLev=LEVEL_ADVANCED):
        form.addSection(label='Optimisation')
        form.addParam('regularisationParamT', params.IntParam, default=4,
                      expertLevel=expertLev,
                      label='Regularisation parameter T',
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

        if not self.IS_VOLSELECTOR:
            form.addParam('doSubsets', params.BooleanParam, default=False,
                          label='Use subsets for initial updates?',
                          help='If set to True, multiple maximization updates '
                               '(as many as defined by the _Number of subset '
                               'updates_) will be performed during the first '
                               'iteration(s): each time after the number of '
                               'particles in a subset has been processed. By '
                               'using subsets with much fewer particles than '
                               'the entire data set, the initial updates '
                               'will be much faster, while the very low '
                               'resolution class averages will not be '
                               'notably worse than with the entire data set. '
                               '\nThis will greatly speed up 2D '
                               'classifications with very many (hundreds of '
                               'thousands or more) particles. A useful '
                               'subset size is probably in the order of ten '
                               'thousand particles. If the data set only '
                               'comprises (tens of) thousands of particles, '
                               'this option may be less useful.')
            form.addParam('subsetSize', params.IntParam, default=10000,
                          condition='doSubsets',
                          label='Initial subset size',
                          help='Number of individual particles after which one '
                               'will perform a maximization update in the first '
                               'iteration(s). A useful subset size is probably '
                               'in the order of ten thousand particles.')
            form.addParam('subsetUpdates', params.IntParam, default=3,
                          condition='doSubsets',
                          label='Number of subset updates',
                          help='This option is only used when a positive '
                               'number is given for the _Initial subset size_. '
                               'In that case, in the first iteration, '
                               'maximization updates are performed over '
                               'a smaller subset of the particles to speed '
                               'up calculations.Useful values are probably in '
                               'the range of 2-5 subset updates. Using more '
                               'might speed up further, but with the risk of '
                               'affecting the results. If the number of subsets '
                               'times the subset size is larger than the number '
                               'of particles in the data set, then more than 1 '
                               'iteration will be split into subsets.')
        form.addParam('limitResolEStep', params.FloatParam, default=-1,
                      expertLevel=LEVEL_ADVANCED,
                      label='Limit resolution E-step to (A)',
                      help='If set to a positive number, then the '
                           'expectation step (i.e. the alignment) will be '
                           'done only including the Fourier components up '
                           'to this resolution (in Angstroms). This is '
                           'useful to prevent overfitting, as the '
                           'classification runs in RELION are not to be '
                           'guaranteed to be 100% overfitting-free (unlike '
                           'the _3D auto-refine_ with its gold-standard '
                           'FSC). In particular for very difficult data '
                           'sets, e.g. of very small or featureless '
                           'particles, this has been shown to give much '
                           'better class averages. In such cases, values '
                           'in the range of 7-12 Angstroms have proven '
                           'useful.')

    def _defineSamplingParams(self, form, expertLev=LEVEL_ADVANCED):
        form.addSection('Sampling')
        if self.IS_AUTOCLASSIFY:
            form.addParam('doImageAlignment', params.BooleanParam, default=True,
                          label='Perform image alignment?',
                          help='If set to No, then rather than performing '
                               'both alignment and classification, only '
                               'classification will be performed. This allows '
                               'the use of very focused masks.This requires '
                               'that the optimal orientations of all '
                               'particles are already calculated.')
        else:
            form.addHidden('doImageAlignment', params.BooleanParam,
                           default=True)

        if self.IS_3D:
            form.addParam('angularSamplingDeg', params.EnumParam, default=1,
                          choices=ANGULAR_SAMPLING_LIST,
                          expertLevel=expertLev, condition='doImageAlignment',
                          label='Angular sampling interval (deg)',
                          help='There are only a few discrete angular samplings'
                               ' possible because we use the HealPix library to'
                               ' generate the sampling of the first two Euler '
                               'angles on the sphere. The samplings are '
                               'approximate numbers and vary slightly over '
                               'the sphere.')
        else:
            form.addParam('inplaneAngularSamplingDeg', params.FloatParam,
                          default=5,
                          label='In-plane angular sampling (deg)',
                          condition="doImageAlignment",
                          help='The sampling rate for the in-plane rotation '
                               'angle (psi) in degrees.\n'
                               'Using fine values will slow down the program. '
                               'Recommended value for\n'
                               'most 2D refinements: 5 degrees. \n\n'
                               'If auto-sampling is used, this will be the '
                               'value for the first \niteration(s) only, and '
                               'the sampling rate will be increased \n'
                               'automatically after that.')

        form.addParam('offsetSearchRangePix', params.FloatParam,
                      default=5, expertLevel=expertLev,
                      condition='doImageAlignment',
                      label='Offset search range (pix)',
                      help='Probabilities will be calculated only for '
                           'translations in a circle with this radius (in '
                           'pixels). The center of this circle changes at '
                           'every iteration and is placed at the optimal '
                           'translation for each image in the previous '
                           'iteration.')
        form.addParam('offsetSearchStepPix', params.FloatParam,
                      default=1.0, expertLevel=expertLev,
                      condition='doImageAlignment',
                      label='Offset search step (pix)',
                      help='Translations will be sampled with this step-size '
                           '(in pixels). Translational sampling is also done '
                           'using the adaptive approach. Therefore, if '
                           'adaptive=1, the translations will first be '
                           'evaluated on a 2x coarser grid.')
        if self.IS_3D:
            form.addParam('localAngularSearch', params.BooleanParam,
                          default=False, expertLevel=expertLev,
                          condition='doImageAlignment',
                          label='Perform local angular search?',
                          help='If set to Yes, then rather than performing '
                               'exhaustive angular searches, local searches '
                               'within the range given below will be performed.'
                               ' A prior Gaussian distribution centered at the '
                               'optimal orientation in the previous iteration '
                               'and with a stddev of 1/3 of the range given '
                               'below will be enforced.')
            form.addParam('localAngularSearchRange', params.FloatParam,
                          default=5.0, expertLevel=expertLev,
                          condition='doImageAlignment and localAngularSearch',
                          label='Local angular search range',
                          help='Local angular searches will be performed '
                               'within +/- the given amount (in degrees) from '
                               'the optimal orientation in the previous '
                               'iteration. A Gaussian prior (also see previous '
                               'option) will be applied, so that orientations '
                               'closer to the optimal orientation in the '
                               'previous iteration will get higher weights '
                               'than those further away.')

    def _defineAdditionalParams(self, form):
        form.addSection('Compute')
        form.addParam('useParallelDisk', params.BooleanParam, default=True,
                      label='Use parallel disc I/O?',
                      help='If set to Yes, all MPI slaves will read '
                           'their own images from disc. Otherwise, only '
                           'the master will read images and send them '
                           'through the network to the slaves. Parallel '
                           'file systems like gluster of fhgfs are good '
                           'at parallel disc I/O. NFS may break with many '
                           'slaves reading in parallel.')
        form.addParam('pooledParticles', params.IntParam, default=3,
                      label='Number of pooled particles:',
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
        if self.IS_3D:
            form.addParam('skipPadding', params.BooleanParam, default=False,
                          label='Skip padding',
                          help='If set to Yes, the calculations will not use '
                               'padding in Fourier space for better '
                               'interpolation in the references. Otherwise, '
                               'references are padded 2x before Fourier '
                               'transforms are calculated. Skipping padding '
                               '(i.e. use --pad 1) gives nearly as good '
                               'results as using --pad 2, but some artifacts '
                               'may appear in the corners from signal that is '
                               'folded back.')

        form.addParam('allParticlesRam', params.BooleanParam, default=False,
                      label='Pre-read all particles into RAM?',
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
        form.addParam('scratchDir', params.PathParam,
                      condition='not allParticlesRam',
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
        form.addParam('combineItersDisc', params.BooleanParam, default=False,
                      label='Combine iterations through disc?',
                      help='If set to Yes, at the end of every iteration '
                           'all MPI slaves will write out a large file '
                           'with their accumulated results. The MPI '
                           'master will read in all these files, combine '
                           'them all, and write out a new file with the '
                           'combined results. All MPI salves will then '
                           'read in the combined results. This reduces '
                           'heavy load on the network, but increases load '
                           'on the disc I/O. This will affect the time it '
                           'takes between the progress-bar in the '
                           'expectation step reaching its end (the mouse '
                           'gets to the cheese) and the start of the '
                           'ensuing maximisation step. It will depend on '
                           'your system setup which is most efficient.')
        form.addParam('doGpu', params.BooleanParam, default=True,
                      label='Use GPU acceleration?',
                      help='If set to Yes, the job will try to use GPU '
                           'acceleration.')
        form.addParam('gpusToUse', params.StringParam, default='',
                      label='Which GPUs to use:', condition='doGpu',
                      help='This argument is not necessary. If left empty, '
                           'the job itself will try to allocate available '
                           'GPU resources. You can override the default '
                           'allocation by providing a list of which GPUs '
                           '(0,1,2,3, etc) to use. MPI-processes are '
                           'separated by ":", threads by ",". '
                           'For example: "0,0:1,1:0,0:1,1"')
        form.addParam('oversampling', params.IntParam, default=1,
                      label="Over-sampling",
                      help="Adaptive oversampling order to speed-up "
                           "calculations (0=no oversampling, 1=2x, 2=4x, etc)")
        form.addParam('extraParams', params.StringParam,
                      default='',
                      label='Additional parameters',
                      help="In this box command-line arguments may be "
                           "provided that are not generated by the GUI. This "
                           "may be useful for testing developmental options "
                           "and/or expert use of the program, e.g:\n"
                           "--dont_combine_weights_via_disc\n"
                           "--verb 1\n"
                           "--pad 2")
        form.addParallelSection(threads=1, mpi=3)

    # -------------------------- INSERT steps functions ------------------------
    def _insertAllSteps(self):
        #already implemented in subclasses
        pass

    def _insertClassifyStep(self, **kwargs):
        """ Prepare the command line arguments before calling Relion. """
        # Join in a single line all key, value pairs of the args dict
        normalArgs = {}
        basicArgs = {}
        self._setNormalArgs(normalArgs)
        self._setBasicArgs(basicArgs)
        if kwargs:
            for key, value in kwargs.items():
                newKey = '--%s' % key
                normalArgs[newKey] = value

        return self._insertFunctionStep('runClassifyStep', normalArgs,
                                        basicArgs, self._rLev)

    # -------------------------- STEPS functions -------------------------------
    def convertInputStep(self, resetDeps, copyAlignment):
        """ Implemented in subclasses. """
        pass

    def runClassifyStep(self, normalArgs, basicArgs, rLev):
        self._createIterTemplates(rLev)  # initialize files to know iterations
        self._setComputeArgs(normalArgs)
        params = self._getParams(normalArgs)
        self._runClassifyStep(params)

        for i in range(10, 55, 5):
            stop = self._stopRunCondition(rLev, i-5)
            if not stop:
                chgMaps = self.getAttributeValue('changeMaps', False)
                if chgMaps:
                    fnPath = self._getFileName('volFind', ruNum=rLev, iter=1)
                    fnList = glob(fnPath)
                    for fn in fnList:
                        classId = int(fn.split('class')[-1].split('.')[0])
                        vol = self._getFileName('volume', ruNum=rLev,
                                                iter=i-5, ref3d=classId)
                        pwpath.copyFile(fn, vol)

                basicArgs['--iter'] = i
                self._setContinueArgs(basicArgs, rLev)
                self._setComputeArgs(basicArgs)
                paramsCont = self._getParams(basicArgs)
                self._runClassifyStep(paramsCont)
            else:
                break

    def _runClassifyStep(self, params):
        """ Execute the relion steps with the give params. """
        self.runJob(self._getProgram(), params)

    def createOutputStep(self):
        """ Implemented in subclasses. """
        pass

    # --------------------------- INFO functions -------------------------------
    def _validate(self):
        errors = []
        self.validatePackageVersion('RELION_CRYOMETHODS_HOME', errors)

        if self._getInputParticles().isOddX():
            errors.append("Relion only works with even values for the "
                          "image dimensions!")

        errors += self._validateNormal()

        return errors

    def _validateNormal(self):
        """ Should be overwritten in subclasses to
        return summary message for NORMAL EXECUTION.
        """
        return []

    def _citations(self):
        cites = []
        return cites

    def _summary(self):
        summary = self._summaryNormal()
        return summary

    def _summaryNormal(self):
        """ Should be overwritten in subclasses to
        return summary message for NORMAL EXECUTION.
        """
        return []



    def _methods(self):
        """ Should be overwritten in each protocol.
        """
        return []

    # -------------------------- UTILS functions ------------------------------
    def _setNormalArgs(self, args):
        maskDiameter = self.maskDiameterA.get()
        pixelSize = self._getPixeSize()

        if maskDiameter <= 0:
            maskDiameter = pixelSize * self._getNewDim()

        self._defineInput(args)
        args['--particle_diameter'] = maskDiameter
        # Since Relion 3.1 --angpix is no longer a valid argument
        if Plugin.IS_RELION_30():
            args['--angpix'] = pixelSize

        self._setCTFArgs(args)

        if self.maskZero == MASK_FILL_ZERO:
            args['--zero_mask'] = ''

        args['--K'] = self.numOfVols.get() if self.IS_VOLSELECTOR \
                      else self.numberOfClasses.get()

        if self.limitResolEStep > 0:
            args['--strict_highres_exp'] = self.limitResolEStep.get()

        if self.IS_3D:
            if not self.isMapAbsoluteGreyScale:
                args['--firstiter_cc'] = ''
            args['--ini_high'] = self.initialLowPassFilterA.get()
            args['--sym'] = self.symmetryGroup.get()
            args['--pad'] = 1 if self.skipPadding else 2
            if Plugin.IS_RELION_GT30():
                # We use the same pixel size as input particles, since
                # we convert anyway the input volume to match same size
                args['--ref_angpix'] = pixelSize

        refArg = self._getRefArg()
        if refArg:
            args['--ref'] = refArg

        self._setBasicArgs(args)

    def _setCTFArgs(self, args):
        # CTF stuff
        if self.doCTF:
            args['--ctf'] = ''

        if self.hasReferenceCTFCorrected:
            args['--ctf_corrected_ref'] = ''

        if self._getInputParticles().isPhaseFlipped():
            args['--ctf_phase_flipped'] = ''

        if self.ignoreCTFUntilFirstPeak:
            args['--ctf_intact_first_peak'] = ''

    def _setSubsetArgs(self, args):
        if self._doSubsets():
            args['--write_subsets'] = 1
            args['--subset_size'] = self.subsetSize.get()
            args['--max_subsets'] = self.subsetUpdates.get()
            if self._useFastSubsets():
                args['--fast_subsets'] = ''

    def _setBasicArgs(self, args):
        """ Return a dictionary with basic arguments. """
        self._defineOutput(args)
        args.update({'--flatten_solvent': '',
                     '--norm': '',
                     '--scale': '',
                     '--oversampling': self.oversampling.get(),
                     '--tau2_fudge': self.regularisationParamT.get()
                     })
        args['--iter'] = 5

        if not self.IS_VOLSELECTOR:
            self._setSubsetArgs(args)

        self._setSamplingArgs(args)
        self._setMaskArgs(args)

    def _setSamplingArgs(self, args):
        """Should be overwritten in subclasses"""
        pass

    def _setMaskArgs(self, args):
        if self.IS_3D:
            if self.referenceMask.hasValue():
                mask = conv.convertMask(self.referenceMask.get(),
                                        self._getTmpPath())
                args['--solvent_mask'] = mask

            if self.solventMask.hasValue():
                solventMask = conv.convertMask(self.solventMask.get(),
                                               self._getTmpPath())
                args['--solvent_mask2'] = solventMask

            if (self.referenceMask.hasValue() and self.solventFscMask):
                args['--solvent_correct_fsc'] = ''

    def _getSamplingFactor(self):
        return 1 if self.oversampling == 0 else 2 * self.oversampling.get()

    def _setComputeArgs(self, args):
        args['--pool'] = self.pooledParticles.get()

        if not self.combineItersDisc:
            args['--dont_combine_weights_via_disc'] = ''

        if not self.useParallelDisk:
            args['--no_parallel_disc_io'] = ''

        if self.allParticlesRam:
            args['--preread_images'] = ''
        else:
            if self._getScratchDir():
                args['--scratch_dir'] = self._getScratchDir()

        if self.doGpu:
            args['--gpu'] = self.gpusToUse.get()
        args['--j'] = self.numberOfThreads.get()

    def _setContinueArgs(self, args, rLev):
        continueIter = self._lastIter(rLev)
        if self.IS_AUTOCLASSIFY:
            args['--continue'] = self._getFileName('optimiser', lev=self._level,
                                                   rLev=rLev, iter=continueIter)
        else:
            args['--continue'] = self._getFileName('optimiser', ruNum=rLev,
                                                   iter=continueIter)

    def _getParams(self, args):
        return ' '.join(['%s %s' % (k, str(v)) for k, v in args.items()])

    def _getScratchDir(self):
        """ Returns the scratch dir value without spaces.
         If none, the empty string will be returned.
        """
        scratchDir = self.scratchDir.get() or ''
        return scratchDir.strip()

    def _getProgram(self, program='relion_refine'):
        """ Get the program name depending on the MPI use or not. """
        if self.numberOfMpi > 1:
            program += '_mpi'
        return program

    def _getInputParticles(self):
        return self.inputParticles.get()

    def _getIterNumber(self, index):
        """ Return the list of iteration files, give the iterTemplate. """
        result = None
        files = sorted(glob(self._iterTemplate))
        if files:
            f = files[index]
            s = self._iterRegex.search(f)
            if s:
                result = int(s.group(1))  # group 1 is 3 digits iteration
                # number
        return result

    def _lastIter(self, rLev=None):
        self._createIterTemplates(rLev)
        return self._getIterNumber(-1)

    def _firstIter(self):
        return self._getIterNumber(0) or 1

    def _splitInCTFGroups(self, imgStar):
        """ Add a new column in the image star to separate the particles
        into ctf groups """
        conv.splitInCTFGroups(imgStar,
                              self.defocusRange.get(),
                              self.numParticles.get())

    def _getnumberOfIters(self):
        return self.numberOfIterations.get()

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
                vol = Volume()
                self._invertScaleVol(fnMrc)
                vol.setFileName(self._getOutputVolFn(fnMrc))
                vol.setObjId(itemId)
                vol._rlnClassDistribution = Float(classDistrib)
                vol._rlnAccuracyRotations = Float(accurracyRot)
                vol._rlnAccuracyTranslations = Float(accurracyTras)
                vol._rlnEstimatedResolution = Float(resol)
                volSet.append(vol)

    def _getRefArg(self):
        """ Return the filename that will be used for the --ref argument.
        The value will depend if in 2D and 3D or if input references will
        be used.
        It will return None if no --ref should be used. """
        if self.IS_3D:
            inputObj = self.inputVolumes.get()
            if isinstance(inputObj, SetOfVolumes):
                # input SetOfVolumes as references
                return self._getRefStar()
        return None  # No --ref should be used at this point

    def _convertVolFn(self, inputVol):
        """ Return a new name if the inputFn is not .mrc """
        index, fn = inputVol.getLocation()
        return self._getTmpPath(replaceBaseExt(fn, '%02d.mrc' % index))

    def _convertVol(self, ih, inputVol):
        outputFn = self._convertVolFn(inputVol)

        if outputFn:
            xdim = self._getNewDim()
            img = ih.read(inputVol)
            img.scale(xdim, xdim, xdim)
            img.write(outputFn)

        return outputFn

    def _getRefStar(self):
        return self._getTmpPath("input_references.star")

    def _convertRef(self):

        ih = ImageHandler()
        inputObj = self.inputVolumes.get()
        row = md.Row()
        refMd = md.MetaData()
        for vol in inputObj:
            newVolFn = self._convertVol(ih, vol)
            row.setValue(md.RLN_MLMODEL_REF_IMAGE, newVolFn)
            row.addToMd(refMd)
        refMd.write(self._getRefStar())

    def _getNewDim(self):
        tgResol = self.getAttributeValue('targetResol', 0)
        partSet = self._getInputParticles()
        size = partSet.getXDim()
        nyquist = 2 * partSet.getSamplingRate()

        if tgResol > nyquist:
            newSize = int(round(size * nyquist / tgResol))
            if newSize % 2 == 1:
                newSize += 1
            return newSize
        else:
            return size

    def _getPixeSize(self):
        partSet = self._getInputParticles()
        oldSize = partSet.getXDim()
        newSize  = self._getNewDim()
        pxSize = partSet.getSamplingRate() * oldSize / newSize
        return pxSize

    def _scaleImages(self,indx, img):
        fn = img.getFileName()
        index = img.getIndex()
        newFn = self._getTmpPath('particles_subset.mrcs')
        xdim = self._getNewDim()

        ih = ImageHandler()
        image = ih.read((index, fn))
        image.scale(xdim, xdim)

        image.write((indx, newFn))

        img.setFileName(newFn)
        img.setIndex(indx)
        img.setSamplingRate(self._getPixeSize())

    def _convertInput(self, imgSet):
        newDim = self._getNewDim()
        bg = int(newDim / 2)

        args = '--operate_on %s --operate_out %s --norm --bg_radius %d'

        params = args % (self._getFileName('input_star'),
                         self._getFileName('preprocess_parts_star'), bg)
        self.runJob(self._getProgram(program='relion_preprocess'), params)

        from pyworkflow.utils import moveFile

        moveFile(self._getFileName('preprocess_parts'),
                 self._getTmpPath('particles_subset.mrcs'))

    def _stopRunCondition(self, rLev, iter):
        x = np.array([])
        y = np.array([])

        for i in range(iter-5, iter+1, 1):
            x = np.append(x, i)
            if self.IS_AUTOCLASSIFY:
                modelFn = self._getFileName('model', iter=i,
                                            lev=self._level, rLev=rLev)
            else:
                modelFn = self._getFileName('model', iter=i, ruNum=rLev)

            modelMd = md.RowMetaData('model_general@' + modelFn)
            y = np.append(y, modelMd.getValue(md.RLN_MLMODEL_AVE_PMAX))

        slope, _, _, _, _ = stats.linregress(x, y)
        return True if slope <= 0.005 else False

    def _invertScaleVol(self, fn):
        xdim = self._getInputParticles().getXDim()
        outputFn = self._getOutputVolFn(fn)
        ih = ImageHandler()
        img = ih.read(fn)
        img.scale(xdim, xdim, xdim)
        img.write(outputFn)

    def _getOutputVolFn(self, fn):
        return replaceExt(fn, '_origSize.mrc')

    def _postprocessImageRow(self, img, imgRow):
        partId = img.getParticleId()
        imgRow.setValue(md.RLN_PARTICLE_ID, int(partId))
        imgRow.setValue(md.RLN_MICROGRAPH_NAME,
                        "%06d@fake_movie_%06d.mrcs"
                        % (img.getFrameId(), img.getMicId()))

    def _postprocessParticleRow(self, part, partRow):
        if part.hasAttribute('_rlnGroupName'):
            partRow['rlnGroupName'] = part.getAttributeValue('_rlnGroupName')
        else:
            partRow['rlnGroupName'] = '%s' % part.getMicId()
        ctf = part.getCTF()
        if ctf is not None and ctf.getPhaseShift():
            partRow['rlnCtfPhaseShift'] = ctf.getPhaseShift()

    def _getResetDeps(self):
        """Should be overwritten in subclasses"""
        pass

    def _doSubsets(self):
        # Since 'doSubsets' property is only valid for 2.1+ protocols
        # we need provide a default value for backward compatibility
        return self.getAttributeValue('doSubsets', False)

    def _copyAlignAsPriors(self, imgStar, alignType):

        from emtable import Table
        mdParts = Table(fileName=imgStar, tableName='particles')
        mdOptics = Table(fileName=imgStar, tableName='optics')	

        # set priors equal to orig. values
        mdParts.addColumns('rlnOriginXPriorAngst=rlnOriginXAngst')
        mdParts.addColumns('rlnOriginYPriorAngst=rlnOriginYAngst')
        mdParts.addColumns('rlnAnglePsiPrior=rlnAnglePsi')

        if alignType == ALIGN_PROJ:
            mdParts.addColumns('rlnAngleRotPrior=rlnAngleRot')
            mdParts.addColumns('rlnAngleTiltPrior=rlnAngleTilt')
        
                        
        with open(imgStar, "w") as f:
            mdParts.writeStar(f, tableName='particles')
            mdOptics.writeStar(f, tableName='optics')

    def _defineInput(self, args):
        args['--i'] = self._getFileName('input_star')

    def _defineOutput(self, args):
        args['--o'] = self._getExtraPath('relion')
