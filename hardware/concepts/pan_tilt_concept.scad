// VisionControl Phase 4.5 — EDITABLE CONCEPT ONLY, NOT FOR FABRICATION.
// All dimensions are illustrative millimetres, NOT measured UGREEN specifications.
// No motor, torque, screw, bearing, cable bend or load capacity is verified.

/* [Illustrative dimensions - mm] */
base_width = 130;
base_depth = 100;
base_height = 16;
camera_width = 82;
camera_depth = 30;
camera_height = 30;
bracket_spacing = 100;
bracket_thickness = 10;
bracket_depth = 20;
support_height = 55;
platform_diameter = 116;
platform_thickness = 8;
mount_plate_thickness = 4;
camera_mount_offset = [0, 0, 0];
pan_motor_size = [30, 30, 20];
tilt_motor_size = [26, 24, 28];

/* [Illustrative motion - degrees] */
pan_deg = 0; // [-45:1:45]
tilt_deg = 0; // [-25:1:25]
pan_limit_deg = 45;
tilt_limit_deg = 25;

/* [Concept indicators] */
show_axes = true;
show_motion_ranges = true;
show_cable_clearance = true;
$fn = 48;

platform_bottom = base_height + pan_motor_size[2] + 4;
platform_top = platform_bottom + platform_thickness;
tilt_pivot_height = platform_top + support_height - 7;

assert(base_width > 0 && base_depth > 0 && base_height > 0);
assert(camera_width > 0 && camera_depth > 0 && camera_height > 0);
assert(bracket_spacing >= camera_width + bracket_thickness + 8);
assert(abs(pan_deg) <= pan_limit_deg && abs(tilt_deg) <= tilt_limit_deg);

module link(a, b, radius=1) {
    hull() {
        translate(a) sphere(r=radius);
        translate(b) sphere(r=radius);
    }
}

module stationary_base() {
    color([0.20, 0.23, 0.27])
        translate([-base_width/2, -base_depth/2, 0])
            cube([base_width, base_depth, base_height]);
    // Approximate PAN motor enclosure. Shape is not a purchased motor outline.
    color([0.22, 0.43, 0.72])
        translate([-pan_motor_size[0]/2, -pan_motor_size[1]/2, base_height])
            cube(pan_motor_size);
    color([0.65, 0.67, 0.70])
        translate([0, 0, base_height + pan_motor_size[2] - 2]) cylinder(h=9, r=5);
}

module tilt_brackets() {
    for (side=[-1,1]) {
        color([0.67, 0.70, 0.74])
            translate([side*bracket_spacing/2-bracket_thickness/2, -bracket_depth/2, platform_top])
                cube([bracket_thickness, bracket_depth, support_height]);
    }
    // Approximate TILT motor outside right bracket; mounting and shaft unverified.
    color([0.22, 0.43, 0.72])
        translate([bracket_spacing/2+bracket_thickness/2, -tilt_motor_size[1]/2,
                   tilt_pivot_height-tilt_motor_size[2]/2]) cube(tilt_motor_size);
}

module camera_cradle() {
    plate_z = camera_mount_offset[2] - camera_height/2 - mount_plate_thickness/2;
    // Plate touches the simplified camera bottom at the default offset.
    color([0.43, 0.47, 0.53])
        translate([camera_mount_offset[0], camera_mount_offset[1], plate_z])
            cube([camera_width+6, camera_depth+8, mount_plate_thickness], center=true);
    for (side=[-1,1]) {
        // Short external cradle ears/pivots; no solid axle through the webcam.
        color([0.43, 0.47, 0.53])
            translate([side*(camera_width/2+1.75), 0, plate_z/2])
                cube([3.5, 12, abs(plate_z)+mount_plate_thickness], center=true);
        color([0.85, 0.57, 0.20])
            translate([side*(camera_width/2+6),0,0]) rotate([0,90,0]) cylinder(h=10,r=3,center=true);
    }
    // Approximate UGREEN-like camera body, intentionally generic and unmeasured.
    color([0.10, 0.12, 0.15]) translate(camera_mount_offset)
        cube([camera_width, camera_depth, camera_height], center=true);
    color([0.20, 0.40, 0.52])
        translate(camera_mount_offset + [0,camera_depth/2+1,0])
            rotate([-90,0,0]) cylinder(h=5,r=8);
    if (show_cable_clearance) {
        // Transparent rear clearance/path indicator, not a verified cable route.
        color([0.9,0.3,0.7,0.3])
            link(camera_mount_offset+[0,-camera_depth/2,0], [0,-camera_depth/2-25,-20], 4);
    }
}

module moving_assembly() {
    // +pan points camera toward world +X; camera's neutral forward direction +Y.
    rotate([0,0,-pan_deg]) {
        color([0.35,0.39,0.43]) translate([0,0,platform_bottom])
            cylinder(h=platform_thickness,d=platform_diameter);
        tilt_brackets();
        translate([0,0,tilt_pivot_height]) {
            // +tilt points down, not a claim about a future servo's polarity.
            rotate([-tilt_deg,0,0]) camera_cradle();
            if (show_axes) color([1,0.58,0.1,0.32])
                rotate([0,90,0]) cylinder(h=bracket_spacing+25,r=1,center=true);
            if (show_motion_ranges) color([1,0.58,0.1,0.4])
                for (a=[-tilt_limit_deg:5:tilt_limit_deg-5])
                    link([-bracket_spacing/2-15,30*cos(a),-30*sin(a)],
                         [-bracket_spacing/2-15,30*cos(a+5),-30*sin(a+5)],0.8);
        }
    }
}

stationary_base();
moving_assembly();
if (show_axes) color([0.95,0.25,0.25,0.4])
    translate([0,0,base_height]) cylinder(h=tilt_pivot_height+20-base_height,r=1);
if (show_motion_ranges) color([0.95,0.25,0.25,0.4])
    for (a=[-pan_limit_deg:5:pan_limit_deg-5])
        link([72*sin(a),72*cos(a),base_height+2],
             [72*sin(a+5),72*cos(a+5),base_height+2],0.8);
