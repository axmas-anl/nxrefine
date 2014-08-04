import numpy as np
from scipy.optimize import minimize
from nexpy.gui.mainwindow import report_error
from nexpy.gui.plotview import plotview
from nexpy.api.nexus import NeXusError, NXfield, NXroot, NXentry, NXdata
from nexpy.api.nexus import NXdetector, NXinstrument, NXmonochromator, NXsample
from nxpeaks.unitcell import unitcell
from nxpeaks import closest

degrees = 180.0 / np.pi
radians = np.pi / 180.0

def find_nearest(array, value):
    idx = (np.abs(array-value)).argmin()
    return array[idx]
 

def rotmat(axis, angle):
    mat = np.eye(3) 
    if angle is None or np.isclose(angle, 0.0):
        return mat
    cang = np.cos(angle*radians)
    sang = np.sin(angle*radians)
    if axis == 1:
        mat = np.array(((1,0,0), (0,cang,-sang), (0, sang, cang)))
    elif axis == 2:
        mat = np.array(((cang,0,sang), (0,1,0), (-sang,0,cang)))
    else:
        mat = np.array(((cang,-sang,0), (sang,cang,0), (0,0,1)))
    return np.matrix(mat)


def vec(x, y=0.0, z=0.0):
    return np.matrix((x, y, z)).T
       

class NXRefine(object):

    def __init__(self, root=None, 
                 a=None, b=None, c=None, alpha=None, beta=None, gamma=None,
                 wavelength=None, distance=None, 
                 yaw=None, pitch=None, roll=None,
                 xc=None, yc=None, symmetry=None, centring=None, 
                 polar_max=None):
        self.root = root
        self.a = a
        self.b = b
        self.c = c
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.wavelength = wavelength
        self.distance = distance
        self.yaw = yaw
        self.pitch = pitch
        self.roll = roll
        self.gonpitch = 0.0
        self.twotheta = 0.0
        self.phi = 0.0
        self.chi = 0.0
        self.xc = xc
        self.yc = yc
        self.symmetry = symmetry
        self.centring = centring
        self.omega_start = 0.0
        self.omega_step = 0.1
        self.xp = None
        self.yp = None
        self.zp = None
        self.x = None
        self.y = None
        self.z = None
        self.polar_angle = None
        self.azimuthal_angle = None
        self.rotation_angle = None
        self.intensity = None
        self.polar_max = None
        self.UBmat = None
        self._unitcell = None
        self.polar_tol = 0.005
        self.data_path = 'entry/data/v'
        self.data_file = None
        self.data_shape = None
        self.output_chunks = None
        
        self.symmetries = ['cubic', 'tetragonal', 'orthorhombic', 'hexagonal', 
                           'monoclinic', 'triclinic']
        self.centrings = ['P', 'A', 'B', 'C', 'I', 'F', 'R']
        
        if self.root:
            self.read_parameters()
        
    def read_parameter(self, path):
        try:
            value = self.root[path].nxdata
            if isinstance(value, np.ndarray) and value.size == 1:
                return np.float32(value)
            else:
                return value
        except NeXusError:
            pass 

    def read_parameters(self, root=None):
        if root:
            self.root = root
        self.a = self.read_parameter('entry/sample/unitcell_a')
        self.b = self.read_parameter('entry/sample/unitcell_b')
        self.c = self.read_parameter('entry/sample/unitcell_c')
        self.alpha = self.read_parameter('entry/sample/unitcell_alpha')
        self.beta = self.read_parameter('entry/sample/unitcell_beta')
        self.gamma = self.read_parameter('entry/sample/unitcell_gamma')
        self.wavelength = self.read_parameter('entry/instrument/monochromator/wavelength')
        self.distance = self.read_parameter('entry/instrument/detector/distance')
        self.yaw = self.read_parameter('entry/instrument/detector/yaw')
        self.pitch = self.read_parameter('entry/instrument/detector/pitch')
        self.roll = self.read_parameter('entry/instrument/detector/roll')
        self.xc = self.read_parameter('entry/instrument/detector/beam_center_x')
        self.yc = self.read_parameter('entry/instrument/detector/beam_center_y')
        self.symmetry = self.read_parameter('entry/sample/unit_cell_group')
        self.centring = self.read_parameter('entry/sample/lattice_centring')
        self.xp = self.read_parameter('entry/sample/peaks/x')
        self.yp = self.read_parameter('entry/sample/peaks/y')
        self.zp = self.read_parameter('entry/sample/peaks/z')
        self.polar_angle = self.read_parameter('entry/sample/peaks/polar_angle')
        self.azimuthal_angle = self.read_parameter('entry/sample/peaks/azimuthal_angle')
        self.intensity = self.read_parameter('entry/sample/peaks/intensity')
        self.pixel_size = self.read_parameter('entry/instrument/detector/pixel_size')
        self.polar_angle = self.read_parameter('entry/sample/peaks/polar_angle')
        self.rotation_angle = self.read_parameter('entry/sample/peaks/rotation_angle')
        self.UBmat = np.matrix(self.read_parameter('entry/sample/orientation_matrix'))
        if isinstance(self.polar_angle, np.ndarray):
            self.polar_max = self.polar_angle.max()

    def write_parameter(self, path, value):
        if value is not None:
            if isinstance(value, basestring):
                try:
                    del self.root[path]
                except NeXusError:
                    pass
            self.root[path] = value

    def write_parameters(self, root=None):
        if root:
            self.root = root
        if 'instrument' not in self.root.entry.entries:
            self.root.entry.instrument = NXinstrument()
        if 'detector' not in self.root.entry.instrument.entries:
            self.root.entry.instrument.detector = NXdetector()
        if 'monochromator' not in self.root.entry.instrument.entries:
            self.root.entry.instrument.monochromator = NXmonochromator()
        if 'sample' not in self.root.entry.entries:
            self.root.entry.sample = NXsample()
        self.write_parameter('entry/sample/unitcell_a', self.a)
        self.write_parameter('entry/sample/unitcell_b', self.b)
        self.write_parameter('entry/sample/unitcell_c', self.c)
        self.write_parameter('entry/sample/unitcell_alpha', self.alpha)
        self.write_parameter('entry/sample/unitcell_beta', self.beta)
        self.write_parameter('entry/sample/unitcell_gamma', self.gamma)
        self.write_parameter('entry/instrument/monochromator/wavelength', self.wavelength)
        self.write_parameter('entry/instrument/detector/distance', self.distance)
        self.write_parameter('entry/instrument/detector/yaw', self.yaw)
        self.write_parameter('entry/instrument/detector/pitch', self.pitch)
        self.write_parameter('entry/instrument/detector/roll', self.roll)
        self.write_parameter('entry/instrument/detector/beam_center_x', self.xc)
        self.write_parameter('entry/instrument/detector/beam_center_y', self.yc)
        self.write_parameter('entry/sample/unit_cell_group', self.symmetry)
        self.write_parameter('entry/sample/lattice_centring', self.centring)
        self.write_parameter('entry/instrument/detector/pixel_size', self.pixel_size)
        self.write_parameter('entry/sample/orientation_matrix', np.array(self.UBmat))
        if self.omega_start is not None and self.omega_step is not None:
            if isinstance(self.z, np.ndarray):
                self.rotation_angle = self.z * self.omega_step + self.omega_start

    def write_settings(self, settings_file, root=None):
        lines = []
        lines.append('parameters.pixelSize = %s;' % self.pixel_size)
        lines.append('parameters.wavelength = %s;'% self.wavelength)
        lines.append('parameters.distance = %s;' % self.distance)
        lines.append('parameters.unitCell = %s;' % list(self.lattice_settings))
        lines.append('parameters.ubMat = %s;' % str(self.UBmat.tolist()))
        lines.append('parameters.oMat = %s;' % str(self.Omat.tolist()))
        lines.append('parameters.oVec = [0,0,0];')
        lines.append('parameters.det0x = %s;' % self.xc)
        lines.append('parameters.det0y = %s;' % self.yc)
        lines.append('parameters.xTrans = [0,0,0];')
        lines.append('parameters.orientErrorDetPitch = %s;' % self.pitch)
        lines.append('parameters.orientErrorDetRoll = %s;' % self.roll)
        lines.append('parameters.orientErrorDetYaw = %s;' % self.yaw)
        lines.append('parameters.orientErrorGonPitch = %s;' % self.gonpitch)
        lines.append('parameters.twoThetaCorrection = 0;')
        lines.append('parameters.twoThetaNom = %s;' % self.twotheta)
        lines.append('parameters.omegaCorrection = 0;')
        lines.append('parameters.omegaStep = %s;' % self.omega_step)
        lines.append('parameters.chiCorrection = 0;')
        lines.append('parameters.chiNom = %s;' % self.chi)
        lines.append('parameters.phiCorrection = 0;')
        lines.append('parameters.phiNom = %s;' % self.phi)
        lines.append('parameters.gridOrigin = %s;' % self.grid_origin)
        lines.append('parameters.gridBasis = %s;' % [[0,0,1],[0,1,0],[1,0,0]])
        lines.append('parameters.gridDim = %s;' % self.grid_step)
        lines.append('parameters.gridOffset =  [0,0,0];')
        lines.append('parameters.extraFlip =  false;')
        lines.append('inputData.dataFileName =  "%s";' % self.data_file)
        lines.append('inputData.dataSetName = "/%s";' % self.data_path)
        lines.append('inputData.chunkSize =  [32,32,32];')
        lines.append('outputData.dataFileName =  "%s";' % self.output_file)
        lines.append('outputData.dataSetName = "/%s";' % self.data_path)
        lines.append('outputData.dimensions = %s;' % list(self.grid_shape))
        lines.append('outputData.chunkSize =  [32,32,32];')
        lines.append('outputData.compression = %s;' % 0)
        lines.append('outputData.hdfChunkSize = %s;' % list(self.output_chunks))
        lines.append('transformer.transformOptions =  0;')
        lines.append('transformer.oversampleX = 1;')
        lines.append('transformer.oversampleY =  1;')
        lines.append('transformer.oversampleZ =  4;')
        f = open(settings_file, 'w')
        f.write('\n'.join(lines))
        f.close()

    def write_angles(self, polar_angles, azimuthal_angles):
        if 'sample' not in self.root.entry.entries:
            self.root.entry.sample = NXsample()
        if 'peaks' not in self.root.entry.sample.entries:
            self.root.entry.sample.peaks = NXdata()
        if 'polar_angle' in self.root.entry.sample.peaks.entries:
            del self.root.entry.sample.peaks['polar_angle']
        if 'azimuthal_angle' in self.root.entry.sample.peaks.entries:
            del self.root.entry.sample.peaks['azimuthal_angle']
        self.write_parameter('entry/sample/peaks/polar_angle', polar_angles)
        self.write_parameter('entry/sample/peaks/azimuthal_angle', azimuthal_angles)
        self.root.entry.sample.peaks.nxsignal = self.root.entry.sample.peaks.azimuthal_angle
        self.root.entry.sample.peaks.nxaxes = self.root.entry.sample.peaks.polar_angle

    def initialize_grid(self):
        self.h_stop = np.round(self.ds_max * self.a)
        h_range = np.round(2*self.h_stop)
        self.h_start = -self.h_stop
        self.h_step = np.round(h_range/1000, 2)
        self.k_stop = np.round(self.ds_max * self.b)
        k_range = np.round(2*self.k_stop)
        self.k_start = -self.k_stop
        self.k_step = np.round(k_range/1000, 2)
        self.l_stop = np.round(self.ds_max * self.c)
        l_range = np.round(2*self.l_stop)
        self.l_start = -self.l_stop
        self.l_step = np.round(l_range/1000, 2)
        self.define_grid()

    def define_grid(self):
        self.h_shape = np.int32(np.round((self.h_stop - self.h_start) / 
                                          self.h_step, 2)) + 1
        self.k_shape = np.int32(np.round((self.k_stop - self.k_start) / 
                                          self.k_step, 2)) + 1
        self.l_shape = np.int32(np.round((self.l_stop - self.l_start) / 
                                          self.l_step, 2)) + 1
        self.grid_origin = [self.l_start, self.k_start, self.h_start]
        self.grid_step = [np.int32(1.0/self.l_step)+1,    
                          np.int32(1.0/self.k_step)+1,
                          np.int32(1.0/self.h_step)+1]
        self.grid_shape = [self.l_shape, self.k_shape, self.h_shape]

    def initialize_output(self, output_file):
        self.output_file = output_file
        root = NXroot(NXentry(NXdata()))
        root.entry.data.h = np.linspace(self.h_start, self.h_stop, self.h_shape) 
        root.entry.data.k = np.linspace(self.k_start, self.k_stop, self.k_shape) 
        root.entry.data.l = np.linspace(self.l_start, self.l_stop, self.l_shape) 
        root.entry.data.v = NXfield(shape=self.grid_shape, dtype=np.float32)
        root.entry.data.v[0,0,0] = 0.0
        self.output_chunks = root.entry.data.v._memfile['data'].chunks
        root.entry.data.nxsignal = root.entry.data.v
        root.entry.data.nxaxes = [root.entry.data.l, 
                                  root.entry.data.k,
                                  root.entry.data.h]
        root.save(self.output_file)       

    def set_symmetry(self):
        if self.symmetry == 'cubic':
            self.c = self.b = self.a
            self.alpha = self.beta = self.gamma = 90.0 
        elif self.symmetry == 'tetragonal':
            self.b = self.a       
            self.alpha = self.beta = self.gamma = 90.0
        elif self.symmetry == 'orthorhombic':
            self.alpha = self.beta = self.gamma = 90.0 
        elif self.symmetry == 'hexagonal':
            self.b = self.a
            self.alpha = self.beta = 90.0 
            self.gamma = 120.0
        elif symmetry == 'monoclinic':
            self.alpha = self.gamma = 90.0

    def guess_symmetry(self):
        if np.isclose(self.alpha, 90.0) and np.isclose(self.beta, 90.0):
            if np.isclose(self.gamma, 90.0):
                if np.isclose(self.a, self.b) and np.isclose(self.a, self.c):
                    return 'cubic'
                elif np.isclose(self.a, self.b):
                    return 'tetragonal'
                else:
                    return 'orthorhombic'
            elif np.isclose(self.gamma, 120.0):
                if np.isclose(self.a, self.b):
                    return 'hexagonal'
                else:
                    return 'triclinic'
        elif np.isclose(self.alpha, 90.0) and np.isclose(self.gamma, 90.0):
            return 'monoclinic'
        else:
            return 'triclinic'

    @property
    def lattice_parameters(self):
        return self.a, self.b, self.c, self.alpha, self.beta, self.gamma

    @property
    def lattice_settings(self):
        return (self.a, self.b, self.c, 
                self.alpha*radians, self.beta*radians, self.gamma*radians)

    @property
    def tilts(self):
        return self.yaw, self.pitch, self.roll

    @property
    def centers(self):
        return self.xc, self.yc

    @property
    def ds_max(self):
        return 2 * np.sin(self.polar_max*radians/2) / self.wavelength

    @property
    def idx(self):
        return list(np.argwhere(self.polar_angle < self.polar_max)[:,0])

    @property
    def unitcell(self):
        if self._unitcell is None or \
           not np.allclose(self._unitcell.lattice_parameters,
                           np.array(self.lattice_parameters)):
           self._unitcell = unitcell(self.lattice_parameters, self.centring)
        self._unitcell.makerings(self.ds_max)
        return self._unitcell

    @property
    def rings(self):
        return 2*np.arcsin(np.array(self.unitcell.ringds)*self.wavelength/2)*degrees

    @property
    def hkls(self):
	    return [self.get_hkl(self.xp[i], self.yp[i], self.zp[i]) 
	            for i in range(self.xp.size)]

    @property
    def Umat(self):
        return self.UBmat * np.linalg.inv(self.Bmat)

    @property
    def Bmat(self):
        """Create a B matrix containing the column basis vectors of the direct unit cell."""
        a, b, c, alpha, beta, gamma = self.lattice_parameters
        alpha = alpha * radians
        beta = beta * radians
        gamma = gamma * radians
        B23 = c*(np.cos(alpha)-np.cos(beta)*np.cos(gamma))/np.sin(gamma)
        B33 = np.sqrt(c**2-(c*np.cos(beta))**2-B23**2)
        mat = np.matrix(((a, 0, 0),
                         (b*np.cos(gamma), b*np.sin(gamma), 0),
                         (c*np.cos(beta), B23, B33)))
        return np.linalg.inv(mat).T

    @property
    def Omat(self):
        """Define the transform that rotates detector axes into lab axes.

        The inverse transforms detector coords into lab coords.
        When all angles are zero,
            +X(det) = -y(lab), +Y(det) = +z(lab), and +Z(det) = -x(lab)
        """
        return np.matrix(((0,0,1), (0,1,0), (-1,0,0)))

    @property
    def Dmat(self):
        """Define the matrix, whose inverse physically orients the detector.

        It also transforms detector coords into lab coords.
        Operation order:    yaw -> pitch -> roll -> twotheta -> gonpitch
        """
        return np.linalg.inv(rotmat(3, self.yaw) *
                             rotmat(2, self.pitch) *
                             rotmat(1, self.roll) *
                             rotmat(3, self.twotheta) *
                             rotmat(2, self.gonpitch))

    def Gmat(self, omega):
        """Define the matrix that physically orients the goniometer head into place
    
        Its inverse transforms lab coords into head coords.
        """
        return (rotmat(3, self.phi) * rotmat(1, self.chi) * rotmat(3, omega) * 
                rotmat(2,self.gonpitch))

    @property
    def Cvec(self):
        return vec(self.xc, self.yc)

    def Dvec(self, omega):
        Svec = vec(0.0)
        return (self.Gmat(omega) * Svec - 
            (rotmat(2,self.gonpitch) * rotmat(3,self.twotheta) * vec(self.distance)))

    @property
    def Evec(self):
        return vec(1.0 / self.wavelength)

    def Gvec(self, x, y, z):
        omega = self.omega_start + self.omega_step * z
        v1 = vec(x, y)
        v2 = self.pixel_size * np.linalg.inv(self.Omat) * (v1 - self.Cvec)
        v3 = np.linalg.inv(self.Dmat) * v2 - self.Dvec(omega)
        return ((v3/np.linalg.norm(v3)) / self.wavelength) - self.Evec

    def set_polar_max(self, polar_max):
        if not isinstance(self.polar_angle, np.ndarray):
            self.polar_angle, self.azimuthal_angle = self.calculate_angles(self.xp, self.yp)
        self.x = []
        self.y = []
        for i in range(self.xp.size):
            if self.polar_angle[i] <= polar_max:
                self.x.append(self.xp[i])
                self.y.append(self.yp[i])
        self.polar_max = polar_max

    def polar(self, x, y):
        Oimat = np.linalg.inv(self.Omat)
        Mat = self.pixel_size * np.linalg.inv(self.Dmat) * Oimat
        peak = Oimat * (vec(x, y) - self.Cvec)
        v = np.linalg.norm(Mat * peak)
        return np.arctan(v / self.distance) * degrees

    def calculate_angles(self, x, y):
        Oimat = np.linalg.inv(self.Omat)
        Mat = self.pixel_size * np.linalg.inv(self.Dmat) * Oimat
        polar_angles = []
        azimuthal_angles = []
        for i in range(len(x)):
            peak = Oimat * (vec(x[i], y[i]) - self.Cvec)
            v = np.linalg.norm(Mat * peak)
            polar_angle = np.arctan(v / self.distance)
            polar_angles.append(polar_angle)
            azimuthal_angles.append(np.arctan2(-peak[1,0], peak[2,0]))
        return np.array(polar_angles)*degrees, np.array(azimuthal_angles)*degrees

    def calculate_rings(self, polar_max=None):
        if polar_max is None:
            polar_max = self.polar_max
        ds_max = 2 * np.sin(polar_max*radians/2) / self.wavelength
        dss = set(sorted([x[0] for x in self.unitcell.gethkls(ds_max)]))
        peaks = []
        for ds in dss:
            peaks.append(2*np.arcsin(self.wavelength*ds/2)*degrees)
        return sorted(peaks)

    def plot_peaks(self, x, y):
        try:
            polar_angles, azimuthal_angles = self.calculate_angles(x, y)
            azimuthal_field = NXfield(azimuthal_angles, name='azimuthal_angle')
            azimuthal_field.long_name = 'Azimuthal Angle'
            polar_field = NXfield(polar_angles, name='polar_angle')
            polar_field.long_name = 'Polar Angle'
            NXdata(azimuthal_field, polar_field, title='Peak Angles').plot()
        except NeXusError as error:
            report_error('Plotting Lattice', error)

    def plot_rings(self, polar_max=None):
        if polar_max is None:
            polar_max = self.polar_max
        peaks = self.calculate_rings(polar_max)
        ymin, ymax = plotview.plot.yaxis.get_limits()
        plotview.figure.axes[0].vlines(peaks, ymin, ymax,
                                       colors='r', linestyles='dotted')
        plotview.redraw()
    
    def refine_parameters(self):    
        p0 = self.initialize_fit()
        result = minimize(self.residuals, p0, method='nelder-mead',
                              options={'xtol': 1e-6, 'disp': True})
        self.finalize_fit(result.x)

    def get_parameters(self, p):
        i = 0
        for key in [x.keys()[0] for x in self.parameters]:
            self.__dict__[key] = p[i]
            i += 1
        self.set_symmetry()

    def residuals(self, p):
        self.get_parameters(p)
        polar_angles, _ = self.calculate_angles(self.x, self.y)
        rings = self.calculate_rings()
        residuals = np.array([find_nearest(rings, polar_angle) - polar_angle 
                              for polar_angle in polar_angles])
        return np.sum(residuals**2)

    def initialize_fit(self):
        return np.array([p.values()[0] for p in self.parameters])

    def finalize_fit(self, p):
        self.get_parameters(p)
        self.set_symmetry()

    def orient(self, i, j):
        ring1 = np.abs(self.polar_angle[i] - self.rings).argmin()
        g1 = np.array(self.Gvec(self.xp[i], self.yp[i], self.zp[i]).T)[0]
        ring2 = np.abs(self.polar_angle[j] - self.rings).argmin()
        g2 = np.array(self.Gvec(self.xp[j], self.yp[j], self.zp[j]).T)[0]
        self.unitcell.orient(ring1, g1, ring2, g2, verbose=1)
        return np.matrix(self.unitcell.UB)

    def get_hkl(self, x, y, z):
        omega = self.omega_start + self.omega_step * z
        if self.UBmat is not None:
            v5 = self.Gvec(x, y, z)
            v6 = np.linalg.inv(self.Umat) * v5
            v7 = np.linalg.inv(self.Bmat) * v6
            return list(np.array(v7.T)[0])

    def get_hkls(self):
        dss = sorted([ringds for ringds in self.unitcell.ringds 
                      if ringds < self.ds_max])
        hkls=[self.unitcell.ringhkls[ds][0] for ds in dss]
        return [(abs(hkl[0]),abs(hkl[1]),abs(hkl[2])) for hkl in hkls]

    def find_ring(self, h, k, l):
        hkl_list = self.unitcell.gethkls(self.ds_max)
        idx = [x[1] for x in hkl_list].index((h,k,l))
        return self.unitcell.ringds.index(hkl_list[idx][0])

    def find_ring_indices(self, ring):
        less = list(np.where(self.polar_angle>self.rings[ring]-self.polar_tol)[0])
        more = list(np.where(self.polar_angle<self.rings[ring]+self.polar_tol)[0])
        return [idx for idx in less if idx in more]

    def xyz(self, i):
        return self.xp[i], self.yp[i], self.zp[i]

    def hkl(self, i):
        return self.get_hkl(self.xp[i], self.yp[i], self.zp[i])

    def Gvs(self, polar_max=None):
        if self.polar_max is None:
            self.polar_max = polar_max
        result = np.array([self.Gvec(self.xp[i], self.yp[i], self.zp[i]) 
                         for i in self.idx])
        result.shape = (len(self.idx),3)
        return result

    def score(self, polar_max=None, tol=0.1):
        if polar_max is not None:
            self.polar_max = polar_max
        cell = self.unitcell
        npks = []
        npk_max = 0
        i_max = 0
        j_max = 0
        UBmat_max = None
        for i in self.idx:
            for j in self.idx:
                if i != j:
                    UBmat = self.orient(i, j)
                    npk = closest.score(np.array(np.linalg.inv(UBmat)), self.Gvs(), tol)
                    if npk > npk_max:
                        npk_max = npk
                        i_max = i
                        j_max = j
                        UBmat_max = UBmat
                    npks.append(npk)
        return npk, i_max, j_max